from __future__ import annotations

"""Créer les menus de vente (côté client) pour 3 magasins (idempotent).

Objectif:
- Créer 2 menus (Riz cantonais, Pad Thaï crevettes) dans chacun des 3 magasins cibles
- Menus: actif=true, commandable=true, prix MVP (9.90 / 11.90)
- Idempotent: si (nom, magasin_id) existe déjà -> ne pas recréer (mais on peut mettre à niveau prix/flags)

IMPORTANT / contrainte modèle actuelle:
- `Recette.menu_id` est NOT NULL et la recette est rattachée à 1 menu.
- On ne peut donc pas "associer" une même recette à 3 menus (un par magasin) sans dupliquer la recette,
  ce qui est interdit par les règles.

=> Ce script crée les Menus dans les 3 magasins (visibles via /api/client/menus),
   mais NE retouche pas aux recettes existantes.

Lancement:
    cd backend
    python -m scripts.creer_menus_vente_3_magasins

"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.referentiel import Magasin, Menu


def normaliser_nom(nom: str) -> str:
    return " ".join(nom.strip().split())


@dataclass(frozen=True)
class MagasinCible:
    id: UUID
    nom: str


MAGASINS: list[MagasinCible] = [
    MagasinCible(UUID("0be7d9d5-8883-41b0-aff3-2dc6a77e76df"), "Carrefour Prigonrieux"),
    MagasinCible(UUID("3994db1d-af25-4141-a64f-27e74b411e0d"), "Carrefour Auguste Comte"),
    MagasinCible(UUID("60a4b99e-e2e3-4909-8b88-74acac5ca4a2"), "Intermarché Bergerac"),
]

MENUS: list[tuple[str, float]] = [
    ("Riz cantonais", 9.90),
    ("Pad Thaï crevettes", 11.90),
]


async def _get_magasin(session, magasin_id: UUID) -> Magasin:
    res = await session.execute(select(Magasin).where(Magasin.id == magasin_id))
    m = res.scalar_one_or_none()
    if m is None:
        raise RuntimeError(f"Magasin introuvable: {magasin_id}")
    return m


async def _get_or_create_menu(session, *, magasin: Magasin, nom: str, prix: float) -> tuple[Menu, bool]:
    nom = normaliser_nom(nom)
    res = await session.execute(select(Menu).where(Menu.magasin_id == magasin.id, Menu.nom == nom))
    menu = res.scalar_one_or_none()
    if menu is None:
        menu = Menu(
            nom=nom,
            description=None,
            prix=float(prix),
            commandable=True,
            actif=True,
            magasin_id=magasin.id,
        )
        session.add(menu)
        await session.flush()
        return menu, True

    # Mise à niveau (idempotent)
    menu.actif = True
    menu.commandable = True
    menu.prix = float(prix)
    return menu, False


async def run() -> None:
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    cree: dict[UUID, int] = {m.id: 0 for m in MAGASINS}
    ignores: dict[UUID, int] = {m.id: 0 for m in MAGASINS}

    async with sm() as session:
        for magasin_cible in MAGASINS:
            magasin = await _get_magasin(session, magasin_cible.id)

            for nom, prix in MENUS:
                _, created = await _get_or_create_menu(session, magasin=magasin, nom=nom, prix=prix)
                if created:
                    cree[magasin.id] += 1
                else:
                    ignores[magasin.id] += 1

        await session.commit()

    await engine.dispose()

    print("\n=== CREATION MENUS VENTE: RÉSUMÉ ===")
    for m in MAGASINS:
        print(f"- {m.nom} ({m.id}) : créés={cree[m.id]}, déjà présents/maj={ignores[m.id]}")

    print("\nNOTE IMPORTANTE (modèle actuel) :")
    print(
        "`Recette.menu_id` est 1:1 (NOT NULL). Sans dupliquer les recettes (interdit), "
        "on ne peut pas associer les mêmes 2 recettes à 3 menus (un par magasin). "
        "Les menus créés sont bien visibles côté client via /api/client/menus."
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
