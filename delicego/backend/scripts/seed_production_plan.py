"""Seed du plan de production journalier (réel + fallback prédictions).

🎯 Objectif
Initialiser la production réelle du jour pour que l’écran Opérations → Production (scan)
soit immédiatement exploitable.

🧠 Règles métier
Pour une date_plan donnée (par défaut: aujourd'hui UTC) :

Pour chaque magasin actif :
- On récupère toutes les ventes réelles du jour (Vente.date_vente::date = date_plan)
- Si le magasin a >= 1 vente réelle ce jour-là => source=real pour CE magasin
  - qte_planifiée(menu) = somme des ventes réelles pour ce menu (0 si aucune vente pour ce menu)
- Sinon (0 vente réelle pour ce magasin ce jour-là) => source=prediction (si activé)
  - qte_planifiée(menu) = prediction_vente.qte_predite (0 si aucune prédiction)

Important : on ne mélange pas réel et prédiction au sein d’un même magasin le même jour.

🧾 Données à créer
Dans les tables utilisées par production-preparation :
- plan_production (magasin_id, date_plan)
- ligne_plan_production (plan_production_id, recette_id, quantite_a_produire)

🟰 Idempotence
- Si le plan (magasin, date) existe déjà : le réutiliser
- Si la ligne (plan, recette) existe déjà : UPDATE quantite_a_produire + mis_a_jour_le
- Sinon : INSERT

⚙️ Contraintes
- SQLAlchemy async
- Ne pas modifier les ventes / menus

Exécution (depuis backend/):
    python -m scripts.seed_production_plan

Options:
    --date-plan YYYY-MM-DD
    --use-predictions / --no-use-predictions
    --predict-if-missing

La DB est lue depuis la config (DATABASE_URL) ou les variables d’environnement.
"""

from __future__ import annotations

import asyncio
import argparse
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.modeles.referentiel import Magasin, Menu
from app.domaine.modeles.ventes_prevision import Vente


DEFAULT_USE_PREDICTIONS = True


@dataclass(frozen=True)
class SeedStats:
    date_plan: date
    nb_plans_crees: int
    nb_lignes_creees: int
    nb_lignes_mises_a_jour: int
    sources_par_magasin: dict[str, str]


def _today_utc() -> date:
    """Date cible par défaut: aujourd’hui en UTC (cohérent avec la plupart des dates DB)."""

    return datetime.now(UTC).date()


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


async def _upsert_ligne(
    session: AsyncSession,
    *,
    plan_id: UUID,
    menu_id: UUID | None,
    recette_id: UUID,
    qte: float,
) -> bool:
    """Upsert idempotent pour la ligne de plan de production.

    Clé logique cible (prioritaire): (plan_production_id, menu_id)
    - Si menu_id est fourni (cas normal): upsert via (plan_id, menu_id).
      => conforme à l'unique partiel DB: (plan_production_id, menu_id) WHERE menu_id IS NOT NULL

    Fallback compat (cas rare / legacy):
    - Si menu_id est NULL: on conserve le comportement historique via (plan_id, recette_id).

    IMPORTANT: sur certaines DB (ex: environnement docker dev), la contrainte unique
    (plan_production_id, recette_id) peut ne pas exister malgré le modèle ORM.
    On implémente donc un upsert "safe" : SELECT -> UPDATE sinon INSERT.

    Retourne True si INSERT, False si UPDATE.
    """

    # 1) Priorité: (plan, menu)
    if menu_id is not None:
        res = await session.execute(
            select(LignePlanProduction).where(
                LignePlanProduction.plan_production_id == plan_id,
                LignePlanProduction.menu_id == menu_id,
            )
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            existing.quantite_a_produire = float(qte)
            # On garde recette_id alimenté pour compat (front/endpoints encore basés dessus)
            if existing.recette_id != recette_id:
                existing.recette_id = recette_id
            existing.mis_a_jour_le = datetime.now(UTC)
            return False

        session.add(
            LignePlanProduction(
                plan_production_id=plan_id,
                menu_id=menu_id,
                recette_id=recette_id,
                quantite_a_produire=float(qte),
            )
        )
        return True

    # 2) Fallback legacy: (plan, recette) si menu_id inconnu/NULL
    res = await session.execute(
        select(LignePlanProduction).where(
            LignePlanProduction.plan_production_id == plan_id,
            LignePlanProduction.recette_id == recette_id,
        )
    )
    existing = res.scalar_one_or_none()
    if existing is not None:
        existing.quantite_a_produire = float(qte)
        existing.mis_a_jour_le = datetime.now(UTC)
        return False

    session.add(
        LignePlanProduction(
            plan_production_id=plan_id,
            recette_id=recette_id,
            menu_id=None,
            quantite_a_produire=float(qte),
        )
    )
    return True


async def _predict_if_missing(*, date_plan: date) -> None:
    """Optionnel: si demandé, tente de générer des prédictions jusqu’à date_plan."""

    # Import local (évite d'alourdir les scripts si pas utilisé)
    from scripts.predict_sales import main_async as predict_main_async

    # On force un horizon suffisant à partir de start-date=date_plan
    # => si la view est en retard, l’inference refusera (ce qui est OK / explicite)
    await predict_main_async(["--start-date", date_plan.isoformat(), "--horizon", "1"])


async def seed_plan_production_journalier(
    *,
    session: AsyncSession,
    date_plan: date | None = None,
    use_predictions: bool = DEFAULT_USE_PREDICTIONS,
    predict_if_missing: bool = False,
) -> SeedStats:
    """Crée/maj les plans/lignes de production du jour.

    - Source "real" par magasin si >=1 vente réelle le jour J.
    - Sinon fallback "prediction" si activé.
    """

    target = date_plan or _today_utc()
    start_dt, end_dt = _day_bounds_utc(target)

    magasins = list((await session.execute(select(Magasin).where(Magasin.actif.is_(True)))).scalars().all())

    nb_plans_crees = 0
    nb_lignes_creees = 0
    nb_lignes_mises_a_jour = 0
    sources_par_magasin: dict[str, str] = {}

    for magasin in magasins:
        # Menus à planifier: actifs & commandables du magasin
        menus = (
            await session.execute(
                select(Menu).where(
                    Menu.magasin_id == magasin.id,
                    Menu.actif.is_(True),
                    Menu.commandable.is_(True),
                )
            )
        ).scalars().all()
        if not menus:
            continue

        menu_ids = [m.id for m in menus]

        # Compte ventes réelles du jour pour décider de la source (par magasin)
        vente_count = (
            await session.execute(
                select(func.count(Vente.id)).where(
                    Vente.magasin_id == magasin.id,
                    Vente.date_vente >= start_dt,
                    Vente.date_vente <= end_dt,
                    Vente.menu_id.is_not(None),
                )
            )
        ).scalar_one()
        has_real_sales = int(vente_count or 0) > 0

        qte_by_menu: dict[UUID, float] = {m.id: 0.0 for m in menus}

        if has_real_sales:
            sources_par_magasin[str(magasin.id)] = "real"
            rows = (
                await session.execute(
                    select(
                        Vente.menu_id,
                        func.coalesce(func.sum(Vente.quantite), 0.0).label("qte"),
                    )
                    .where(
                        Vente.magasin_id == magasin.id,
                        Vente.date_vente >= start_dt,
                        Vente.date_vente <= end_dt,
                        Vente.menu_id.is_not(None),
                    )
                    .group_by(Vente.menu_id)
                )
            ).all()
            for mid, qte in rows:
                if mid is None:
                    continue
                qte_by_menu[mid] = float(qte or 0.0)
        else:
            if not use_predictions:
                sources_par_magasin[str(magasin.id)] = "none"
            else:
                sources_par_magasin[str(magasin.id)] = "prediction"
                # Si demandé, on tente de générer la prédiction pour date_plan si absente
                if predict_if_missing:
                    exists_pred = (
                        await session.execute(
                            text(
                                """
                                SELECT 1
                                FROM prediction_vente
                                WHERE magasin_id = :magasin_id
                                  AND date_jour = :date_jour
                                LIMIT 1
                                """
                            ),
                            {"magasin_id": str(magasin.id), "date_jour": target},
                        )
                    ).first()
                    if exists_pred is None:
                        await _predict_if_missing(date_plan=target)

                pred_rows = (
                    await session.execute(
                        text(
                            """
                            SELECT menu_id, qte_predite
                            FROM prediction_vente
                            WHERE magasin_id = :magasin_id
                              AND date_jour = :date_jour
                            """
                        ),
                        {"magasin_id": str(magasin.id), "date_jour": target},
                    )
                ).all()
                pred_by_menu = {UUID(str(mid)): float(qte or 0.0) for mid, qte in pred_rows}
                for mid in menu_ids:
                    qte_by_menu[mid] = float(pred_by_menu.get(mid, 0.0))

        # Plan du jour (idempotent)
        plan, created = await _get_or_create_plan(session, magasin_id=magasin.id, date_plan=target)
        if created:
            nb_plans_crees += 1

        # Upsert des lignes (1 par menu actif/commandable)
        for m in menus:
            recette_id = m.recette_id
            if recette_id is None:
                continue
            qte = float(qte_by_menu.get(m.id, 0.0))

            inserted = await _upsert_ligne(
                session,
                plan_id=plan.id,
                menu_id=m.id,
                recette_id=recette_id,
                qte=qte,
            )
            if inserted:
                nb_lignes_creees += 1
            else:
                nb_lignes_mises_a_jour += 1

        print(f"[seed_production_plan] magasin={magasin.id} source={sources_par_magasin[str(magasin.id)]}")

    return SeedStats(
        date_plan=target,
        nb_plans_crees=nb_plans_crees,
        nb_lignes_creees=nb_lignes_creees,
        nb_lignes_mises_a_jour=nb_lignes_mises_a_jour,
        sources_par_magasin=sources_par_magasin,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DéliceGo - seed plan de production (réel + fallback prédictions)")
    p.add_argument("--date-plan", type=str, default=None, help="Date du plan (YYYY-MM-DD)")
    p.add_argument(
        "--use-predictions",
        dest="use_predictions",
        action="store_true",
        default=DEFAULT_USE_PREDICTIONS,
        help="Utiliser prediction_vente si pas de ventes réelles (défaut: True)",
    )
    p.add_argument(
        "--no-use-predictions",
        dest="use_predictions",
        action="store_false",
        help="Désactiver l'usage des prédictions (fallback => 0)",
    )
    p.add_argument(
        "--predict-if-missing",
        action="store_true",
        default=False,
        help="Si aucune prediction_vente n'existe pour date_plan, lancer scripts.predict_sales",
    )
    return p.parse_args(argv)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except Exception as e:
        raise SystemExit(f"--date-plan invalide: {s}. Attendu YYYY-MM-DD. Détail: {e}")


def _database_url() -> str:
    # Priorité : env explicite -> config application
    return os.getenv("DATABASE_URL", str(parametres_application.url_base_donnees))


async def main() -> None:
    url = _database_url()

    args = _parse_args()
    date_plan = _parse_date(args.date_plan) if args.date_plan else None

    engine = create_async_engine(url, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        async with session.begin():
            stats = await seed_plan_production_journalier(
                session=session,
                date_plan=date_plan,
                use_predictions=bool(args.use_predictions),
                predict_if_missing=bool(args.predict_if_missing),
            )

    await engine.dispose()

    print(
        "[seed_production_plan] date_plan=",
        stats.date_plan,
        "plans_crees=",
        stats.nb_plans_crees,
        "lignes_creees=",
        stats.nb_lignes_creees,
        "lignes_maj=",
        stats.nb_lignes_mises_a_jour,
    )


if __name__ == "__main__":
    asyncio.run(main())


# -----------------------------------------------------------------------------
# Requêtes SQL de contrôle (transition vers menu_id)
# -----------------------------------------------------------------------------
# 1) Compter les lignes encore sans menu_id (non backfill car ambiguës ou manquantes)
#
# SELECT count(*) AS nb_lignes_menu_id_null
# FROM ligne_plan_production
# WHERE menu_id IS NULL;
#
# 2) Détecter les recettes ambigües (plusieurs menus pour une même recette dans un magasin)
#
# SELECT magasin_id, recette_id, count(*) AS nb_menus
# FROM menu
# GROUP BY magasin_id, recette_id
# HAVING count(*) > 1
# ORDER BY nb_menus DESC, magasin_id;

