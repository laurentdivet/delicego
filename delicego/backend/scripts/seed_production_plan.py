"""Seed du plan de production journalier (réel).

🎯 Objectif
Initialiser la production réelle du jour pour que l’écran Opérations → Production (scan)
soit immédiatement exploitable.

🧠 Règles métier (STRICTES)
Pour chaque magasin :
- Récupérer les ventes des 14 derniers jours (incluant aujourd’hui, fenêtre glissante)
- Grouper par menu_id
- Calculer :
  moyenne_journaliere = total_quantite / 14
  a_produire = max(1, round(moyenne_journaliere))
- Si un menu n’a aucune vente → ne pas le produire

🧾 Données à créer
Dans les tables utilisées par production-preparation :
- plan_production (magasin_id, date_plan)
- ligne_plan_production (plan_production_id, recette_id, quantite_a_produire)

🟰 Idempotence
- Si le plan (magasin, date) existe déjà : ne pas le recréer
- Si la ligne (plan, recette) existe déjà : ne pas la recréer

⚙️ Contraintes
- SQLAlchemy async
- Ne pas modifier les ventes / menus

Exécution (depuis backend/):
    python -m scripts.seed_production_plan

La DB est lue depuis la config (DATABASE_URL) ou les variables d’environnement.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.modeles.referentiel import Magasin, Menu
from app.domaine.modeles.ventes_prevision import Vente


NB_JOURS = 14

# Par défaut: aujourd'hui.
# NOTE: en environnement dev, le seed de ventes peut être daté (ex: 2025-01-01..03).
# Pour respecter l'objectif "production réelle du jour" tout en rendant l'écran exploitable
# dès maintenant, on peut activer ce fallback.
# - Si aucune vente sur les 14 derniers jours, on prend la date de la vente la plus récente.
FALLBACK_TO_LAST_SALE_DATE_IF_NO_SALES = True


@dataclass(frozen=True)
class SeedStats:
    date_plan: date
    nb_plans_crees: int
    nb_lignes_creees: int


def _today_local_coherent() -> date:
    """Date cible: aujourd’hui (cohérent local).

    Le backend manipule beaucoup d’horodatages en UTC; ici on seed un *jour*.
    On prend donc la date locale (système) pour rester aligné avec l'usage opérateur.
    """

    return datetime.now().date()


def _day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """Bornes UTC d’un jour civil d.

    La colonne `Vente.date_vente` est timezone-aware. On filtre en UTC.
    """

    start = datetime.combine(d, time.min).replace(tzinfo=timezone.utc)
    end = datetime.combine(d, time.max).replace(tzinfo=timezone.utc)
    return start, end


async def _get_or_create_plan(session: AsyncSession, *, magasin_id: UUID, date_plan: date) -> tuple[PlanProduction, bool]:
    res = await session.execute(
        select(PlanProduction).where(PlanProduction.magasin_id == magasin_id, PlanProduction.date_plan == date_plan)
    )
    plan = res.scalar_one_or_none()
    if plan is not None:
        return plan, False

    plan = PlanProduction(magasin_id=magasin_id, date_plan=date_plan)
    session.add(plan)
    await session.flush()  # obtenir plan.id
    return plan, True


async def _ligne_exists(session: AsyncSession, *, plan_id: UUID, recette_id: UUID) -> bool:
    res = await session.execute(
        select(LignePlanProduction.id).where(
            LignePlanProduction.plan_production_id == plan_id,
            LignePlanProduction.recette_id == recette_id,
        )
    )
    return res.scalar_one_or_none() is not None


async def seed_plan_production_journalier(*, session: AsyncSession, date_plan: date | None = None) -> SeedStats:
    """Crée les plans/lignes de production du jour selon la logique demandée."""

    target = date_plan or _today_local_coherent()

    # Fenêtre glissante de 14 jours incluant le jour cible.
    start_day = target - timedelta(days=NB_JOURS - 1)
    start_dt, _ = _day_bounds_utc(start_day)
    _, end_dt = _day_bounds_utc(target)

    if FALLBACK_TO_LAST_SALE_DATE_IF_NO_SALES:
        # Si la base ne contient pas de ventes récentes (ex: seed historique),
        # on seed sur la date de la dernière vente pour rendre l'écran utilisable.
        res = await session.execute(select(func.max(Vente.date_vente)))
        last_dt = res.scalar_one_or_none()
        if last_dt is not None:
            last_date = last_dt.date()
            if last_date != target:
                # On vérifie qu'il n'y a vraiment aucune vente dans la fenêtre courante.
                res2 = await session.execute(
                    select(func.count(Vente.id)).where(Vente.date_vente >= start_dt, Vente.date_vente <= end_dt)
                )
                if int(res2.scalar_one() or 0) == 0:
                    target = last_date
                    start_day = target - timedelta(days=NB_JOURS - 1)
                    start_dt, _ = _day_bounds_utc(start_day)
                    _, end_dt = _day_bounds_utc(target)

    # Tous les magasins.
    magasins = list((await session.execute(select(Magasin))).scalars().all())

    nb_plans_crees = 0
    nb_lignes_creees = 0

    for magasin in magasins:
        # On agrège les ventes sur la période, par menu.
        q = (
            select(
                Vente.menu_id,
                func.coalesce(func.sum(Vente.quantite), 0.0).label("qte"),
            )
            .select_from(Vente)
            .where(
                Vente.magasin_id == magasin.id,
                Vente.date_vente >= start_dt,
                Vente.date_vente <= end_dt,
                Vente.menu_id.is_not(None),
            )
            .group_by(Vente.menu_id)
        )
        rows = (await session.execute(q)).all()

        # Si aucun menu vendu -> rien à produire pour ce magasin.
        if not rows:
            continue

        # Plan du jour (idempotent)
        plan, created = await _get_or_create_plan(session, magasin_id=magasin.id, date_plan=target)
        if created:
            nb_plans_crees += 1

        # Charge les menus concernés et map menu->recette
        menu_ids: list[UUID] = [mid for (mid, _) in rows if mid is not None]
        if not menu_ids:
            continue

        menus_res = await session.execute(select(Menu).where(Menu.id.in_(menu_ids)))
        menus = {m.id: m for m in menus_res.scalars().all()}

        for menu_id, total_qte in rows:
            if menu_id is None:
                continue
            total_qte = float(total_qte or 0.0)
            if total_qte <= 0:
                # "Si un menu n’a aucune vente → ne pas le produire"
                continue

            menu = menus.get(menu_id)
            if menu is None:
                # menu supprimé/incohérent: on ignore sans créer de ligne
                continue

            recette_id = menu.recette_id
            if recette_id is None:
                continue

            moyenne = total_qte / float(NB_JOURS)
            a_produire = max(1, int(round(moyenne)))

            # Ligne idempotente : (plan, recette)
            if await _ligne_exists(session, plan_id=plan.id, recette_id=recette_id):
                continue

            session.add(
                LignePlanProduction(
                    plan_production_id=plan.id,
                    recette_id=recette_id,
                    quantite_a_produire=float(a_produire),
                )
            )
            nb_lignes_creees += 1

    return SeedStats(date_plan=target, nb_plans_crees=nb_plans_crees, nb_lignes_creees=nb_lignes_creees)


def _database_url() -> str:
    # Priorité : env explicite -> config application
    return os.getenv("DATABASE_URL", str(parametres_application.url_base_donnees))


async def main() -> None:
    url = _database_url()

    engine = create_async_engine(url, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        async with session.begin():
            stats = await seed_plan_production_journalier(session=session)

    await engine.dispose()

    print(
        "[seed_production_plan] date_plan=",
        stats.date_plan,
        "plans_crees=",
        stats.nb_plans_crees,
        "lignes_creees=",
        stats.nb_lignes_creees,
    )


if __name__ == "__main__":
    asyncio.run(main())
