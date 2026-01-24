from __future__ import annotations

"""Seed des ventes *réelles* (historiques) pour DéliceGo.

🎯 Objectif
- Créer des ventes réalistes considérées comme vraies (source de vérité)
- Alimenter immédiatement dashboards / prévisions / exploitation

⚙️ Contraintes
- SQLAlchemy async uniquement
- Script idempotent
- Ne pas modifier les endpoints
- Ne pas modifier `seed_real_data.py`

Lancement (depuis backend)
-------------------------
export ENV=dev
export DATABASE_URL_DEV="postgresql+asyncpg://lolo@localhost:5432/delicego_dev"
export DATABASE_URL_TEST="$DATABASE_URL_DEV"
export DATABASE_URL_PROD="$DATABASE_URL_DEV"

python -m scripts.seed_sales_realistic

Idempotence
-----------
Une vente est considérée comme existante si :
- même magasin_id
- même menu_id
- même jour (date tronquée)
- même canal
=> si existe : on ne recrée pas.

"""

import asyncio
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.enums.types import CanalVente
from app.domaine.modeles.referentiel import Magasin, Menu
from app.domaine.modeles.ventes_prevision import Vente


# ------------------------------
# Paramètres métier
# ------------------------------

FENETRE_JOURS = 14  # J-14 -> aujourd'hui (inclus)

COEFF_MAGASIN: dict[str, float] = {
    "Carrefour Market Prigonrieux": 1.0,
    "Carrefour Market Auguste-Comté": 1.0,
    "Intermarché Verrouille": 1.2,
}

BEST_SELLER_KEYWORDS = [
    "pad thai",
    "porc au caramel",
    "riz cantonais",
    "bo bun",
    "ramen",
    "nouilles",
    "curry",
]

MOYEN_KEYWORDS = [
    "sushi saumon",
    "sushi thon",
    "california",
    "maki",
    "poke",
    "chirashi",
    "wok",
]

# Plages *par magasin* sur 14 jours
PLAGE_BEST = (8, 14)
PLAGE_MOYEN = (4, 7)
PLAGE_FAIBLE = (2, 3)


# ------------------------------
# Helpers
# ------------------------------


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def _categorie_menu(nom_menu: str) -> str:
    nom = (nom_menu or "").lower()
    if any(k in nom for k in BEST_SELLER_KEYWORDS):
        return "best"
    if any(k in nom for k in MOYEN_KEYWORDS):
        return "moyen"
    return "faible"


def _tirer_nb_ventes(categorie: str, *, coeff: float, rng: random.Random) -> int:
    if categorie == "best":
        a, b = PLAGE_BEST
    elif categorie == "moyen":
        a, b = PLAGE_MOYEN
    else:
        a, b = PLAGE_FAIBLE

    n = rng.randint(a, b)
    # Coefficient magasin (ex: 1.2)
    n = int(round(n * coeff))
    return max(2, n)  # règle générale: au moins 2


def _tirer_quantite(rng: random.Random) -> int:
    # 70% -> 1, 20% -> 2, 10% -> 3
    r = rng.random()
    if r < 0.70:
        return 1
    if r < 0.90:
        return 2
    return 3


def _random_time_in_window(
    rng: random.Random,
    *,
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
) -> time:
    start = start_h * 60 + start_m
    end = end_h * 60 + end_m
    minute = rng.randint(start, end)
    return time(hour=minute // 60, minute=minute % 60, tzinfo=UTC)


def _tirer_datetime_realiste(jour: date, *, rng: random.Random) -> datetime:
    # Midi majoritaire (11h30-13h30), soir minoritaire (18h30-20h00)
    if rng.random() < 0.78:
        t = _random_time_in_window(rng, start_h=11, start_m=30, end_h=13, end_m=30)
    else:
        t = _random_time_in_window(rng, start_h=18, start_m=30, end_h=20, end_m=0)
    return datetime.combine(jour, t).astimezone(UTC)


def _tirer_jour_sur_fenetre(*, rng: random.Random, debut: date, fin: date) -> date:
    # Weekend: +30% probabilité
    # On fait un tirage pondéré simple sur chaque jour.
    jours: list[date] = []
    weights: list[float] = []

    d = debut
    while d <= fin:
        jours.append(d)
        is_weekend = d.weekday() >= 5  # 5=Sat, 6=Sun
        weights.append(1.3 if is_weekend else 1.0)
        d += timedelta(days=1)

    return rng.choices(jours, weights=weights, k=1)[0]


async def _vente_existe(
    *,
    session,
    magasin_id: UUID,
    menu_id: UUID,
    jour: date,
    canal: CanalVente,
) -> bool:
    debut_dt = datetime.combine(jour, time.min).replace(tzinfo=UTC)
    fin_dt = datetime.combine(jour, time.max).replace(tzinfo=UTC)

    res = await session.execute(
        select(Vente.id).where(
            Vente.magasin_id == magasin_id,
            Vente.menu_id == menu_id,
            Vente.canal == canal,
            Vente.date_vente >= debut_dt,
            Vente.date_vente <= fin_dt,
        )
    )
    return res.scalar_one_or_none() is not None


# ------------------------------
# Main
# ------------------------------


@dataclass(frozen=True)
class SeedStats:
    created_total: int
    created_by_magasin: dict[str, int]
    top_menus: list[tuple[str, float]]
    periode_debut: date
    periode_fin: date


async def seed_sales_realistic() -> SeedStats:
    # IMPORTANT: l'app n'implémente pas de résolution ENV/DATABASE_URL_*.
    # On force donc `DATABASE_URL_DEV` sur `url_base_donnees` via la commande d'exécution.
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    today_utc = datetime.now(UTC).date()
    debut = today_utc - timedelta(days=FENETRE_JOURS)
    fin = today_utc

    rng = random.Random(42)  # déterministe (idempotence + cohérence)

    created_total = 0
    created_by_magasin: dict[str, int] = defaultdict(int)
    menu_qty_counter: Counter[str] = Counter()

    async with sm() as session:
        # Charge magasins et menus
        magasins = (await session.execute(select(Magasin).where(Magasin.actif.is_(True)))).scalars().all()
        if not magasins:
            raise RuntimeError("Aucun magasin actif trouvé. Exécuter d'abord `python -m scripts.seed_real_data`.")

        # On seed uniquement les menus commandables & actifs (ceux utilisés côté client)
        menus = (await session.execute(select(Menu).where(Menu.actif.is_(True), Menu.commandable.is_(True)))).scalars().all()
        if not menus:
            raise RuntimeError("Aucun menu actif/commandable trouvé. Exécuter d'abord `python -m scripts.seed_real_data`.")

        # Menus par magasin (menu.magasin_id)
        menus_par_magasin: dict[UUID, list[Menu]] = defaultdict(list)
        for m in menus:
            menus_par_magasin[m.magasin_id].append(m)

        for magasin in magasins:
            coeff = float(COEFF_MAGASIN.get(magasin.nom, 1.0))
            menus_mag = menus_par_magasin.get(magasin.id, [])
            if not menus_mag:
                # magasin actif mais sans menus: on skip
                continue

            for menu in menus_mag:
                cat = _categorie_menu(menu.nom)
                nb = _tirer_nb_ventes(cat, coeff=coeff, rng=rng)

                # Pour l'idempotence basée sur le jour, on tire des jours *distincts*
                # autant que possible dans la fenêtre.
                jours: set[date] = set()
                safety = 0
                while len(jours) < nb and safety < nb * 20:
                    jours.add(_tirer_jour_sur_fenetre(rng=rng, debut=debut, fin=fin))
                    safety += 1

                # Si la fenêtre est trop petite pour avoir nb jours distincts, on complète (rare ici).
                jours_list = list(jours)
                while len(jours_list) < nb:
                    jours_list.append(_tirer_jour_sur_fenetre(rng=rng, debut=debut, fin=fin))

                for jour in jours_list[:nb]:
                    # Enum DB actuel: INTERNE / EXTERNE / AUTRE
                    # (la valeur "COMPTOIR" n'existe pas dans `delicego_dev`)
                    canal = CanalVente.INTERNE

                    # Idempotence: même (magasin, menu, jour, canal)
                    if await _vente_existe(
                        session=session,
                        magasin_id=magasin.id,
                        menu_id=menu.id,
                        jour=jour,
                        canal=canal,
                    ):
                        continue

                    qte = float(_tirer_quantite(rng))
                    dt = _tirer_datetime_realiste(jour, rng=rng)

                    session.add(
                        Vente(
                            magasin_id=magasin.id,
                            menu_id=menu.id,
                            date_vente=dt,
                            quantite=qte,
                            canal=canal,
                        )
                    )

                    created_total += 1
                    created_by_magasin[magasin.nom] += 1
                    menu_qty_counter[menu.nom] += qte

        await session.commit()

    await engine.dispose()

    top_menus = menu_qty_counter.most_common(5)
    return SeedStats(
        created_total=created_total,
        created_by_magasin=dict(created_by_magasin),
        top_menus=[(k, float(v)) for k, v in top_menus],
        periode_debut=debut,
        periode_fin=fin,
    )


def main() -> None:
    stats = asyncio.run(seed_sales_realistic())

    print("\n=== SEED SALES REALISTIC: RÉSUMÉ ===")
    print(f"Période couverte: {stats.periode_debut.isoformat()} -> {stats.periode_fin.isoformat()} (UTC)")
    print(f"Ventes créées: {stats.created_total}")

    print("\nVentes créées par magasin:")
    if stats.created_by_magasin:
        for nom, nb in sorted(stats.created_by_magasin.items(), key=lambda x: x[0]):
            print(f"- {nom}: {nb}")
    else:
        print("- (0)")

    print("\nTop 5 menus les plus vendus (quantité agrégée):")
    if stats.top_menus:
        for nom, qte in stats.top_menus:
            print(f"- {nom}: {qte:.0f}")
    else:
        print("- (aucun)")


if __name__ == "__main__":
    main()
