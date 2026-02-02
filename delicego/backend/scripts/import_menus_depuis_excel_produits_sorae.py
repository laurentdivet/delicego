from __future__ import annotations

"""Import des menus depuis l'Excel PRODUITS_SORAE.xlsx.

Objectif
--------
Lire l'Excel, et pour chaque ligne créer :
- une Recette (globale) si elle n'existe pas (nom = DESIGNATION)
- un Menu (local magasin) lié à la recette, avec :
  - nom = DESIGNATION
  - prix = PRIX
  - gencode = EAN13 (fallback si vide)
  - description = CONTENANT (fallback COMPOSITION)
Puis commit à la fin.

⚠️ Note importante sur le modèle
--------------------------------
Dans ce projet, `Menu` a des champs obligatoires `magasin_id` et `recette_id`.
Donc ce script a besoin d'un magasin cible (UUID) via variable d'environnement
`IMPORT_MAGASIN_ID`.

Lancement
---------
    cd backend
    export IMPORT_MAGASIN_ID="...uuid..."
    python -m scripts.import_menus_depuis_excel_produits_sorae --excel ../PRODUITS_SORAE.xlsx

Optionnel:
    export DATABASE_URL="postgresql+asyncpg://..."  (sinon .env ou défaut app)

Idempotence
-----------
Relançable : on upsert les menus par (magasin_id, gencode) si gencode présent,
sinon fallback par (magasin_id, nom).
"""

import argparse
import asyncio
import os
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.referentiel import Magasin, Menu, Recette


EXCEL_SHEET = "PRODUITS"


def _normaliser_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v)
    s = s.replace("\xa0", " ")
    s = " ".join(s.strip().split())
    return s or None


def _parse_prix(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, float) and pd.isna(v):
        return 0.0
    # pandas lit PRIX en float la plupart du temps
    try:
        return float(v)
    except Exception:
        s = _normaliser_str(v) or "0"
        s = s.replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0


def _parse_ean13(v: Any) -> str | None:
    s = _normaliser_str(v)
    if not s:
        return None
    # Excel peut convertir en nombre -> string style "3.760275330109e+12"
    # On tente une conversion "safe" vers int.
    try:
        if "e+" in s.lower() or "." in s:
            n = int(float(s))
            s = str(n)
    except Exception:
        pass
    s = "".join(ch for ch in s if ch.isdigit())
    return s or None


async def _get_magasin(session, magasin_id: str) -> Magasin:
    q = await session.execute(select(Magasin).where(Magasin.id == magasin_id))
    magasin = q.scalar_one_or_none()
    if not magasin:
        raise RuntimeError(
            f"Magasin introuvable: {magasin_id}. "
            "Renseigne IMPORT_MAGASIN_ID avec un UUID existant en base."
        )
    return magasin


async def _get_or_create_recette(session, nom: str) -> Recette:
    q = await session.execute(select(Recette).where(Recette.nom == nom))
    recette = q.scalar_one_or_none()
    if recette:
        return recette

    recette = Recette(nom=nom)
    session.add(recette)
    await session.flush()
    return recette


async def _get_menu_by_gencode(session, magasin_id, gencode: str) -> Menu | None:
    q = await session.execute(
        select(Menu).where(Menu.magasin_id == magasin_id).where(Menu.gencode == gencode)
    )
    return q.scalar_one_or_none()


async def _get_menu_by_nom(session, magasin_id, nom: str) -> Menu | None:
    q = await session.execute(select(Menu).where(Menu.magasin_id == magasin_id).where(Menu.nom == nom))
    return q.scalar_one_or_none()


async def importer(excel_path: str, dry_run: bool, limit: int | None) -> None:
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    moteur = create_async_engine(url_db, pool_pre_ping=True)
    sessionmaker_ = async_sessionmaker(bind=moteur, expire_on_commit=False)

    magasin_id = os.getenv("IMPORT_MAGASIN_ID")
    if not magasin_id:
        raise RuntimeError(
            "Variable d'environnement IMPORT_MAGASIN_ID manquante. "
            "Ex: export IMPORT_MAGASIN_ID='...uuid...'"
        )

    # Lecture Excel (en amont, hors session) pour fail-fast si fichier / sheet KO.
    df = pd.read_excel(excel_path, sheet_name=EXCEL_SHEET)
    if limit:
        df = df.head(limit)

    async with sessionmaker_() as session:
        magasin = await _get_magasin(session, magasin_id)

        nb_crees = 0
        nb_maj = 0

        for _, row in df.iterrows():
            nom = _normaliser_str(row.get("DESIGNATION"))
            if not nom:
                continue

            prix = _parse_prix(row.get("PRIX"))
            gencode = _parse_ean13(row.get("EAN13"))

            contenant = _normaliser_str(row.get("CONTENANT"))
            composition = _normaliser_str(row.get("COMPOSITION"))
            description = contenant or (composition[:500] if composition else None)

            recette = await _get_or_create_recette(session, nom=nom)

            menu: Menu | None = None
            if gencode:
                menu = await _get_menu_by_gencode(session, magasin.id, gencode)
            if menu is None:
                menu = await _get_menu_by_nom(session, magasin.id, nom)

            if menu is None:
                menu = Menu(
                    nom=nom,
                    prix=prix,
                    description=description,
                    actif=True,
                    commandable=True,
                    magasin_id=magasin.id,
                    recette_id=recette.id,
                )
                # On force le gencode si présent (sinon default AUTO-...)
                if gencode:
                    menu.gencode = gencode

                session.add(menu)
                nb_crees += 1
            else:
                menu.nom = nom
                menu.prix = prix
                menu.description = description
                menu.actif = True
                menu.commandable = True
                menu.recette_id = recette.id
                if gencode:
                    menu.gencode = gencode
                nb_maj += 1

        if dry_run:
            await session.rollback()
            print(
                f"[DRY RUN] magasin={magasin.nom} ({magasin.id}) | "
                f"menus créés={nb_crees} | menus maj={nb_maj} | total traités={len(df)}"
            )
        else:
            await session.commit()
            print(
                f"Import terminé. magasin={magasin.nom} ({magasin.id}) | "
                f"menus créés={nb_crees} | menus maj={nb_maj} | total traités={len(df)}"
            )

    await moteur.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--excel",
        default="../PRODUITS_SORAE.xlsx",
        help="Chemin du fichier Excel (par défaut: ../PRODUITS_SORAE.xlsx)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'écrit rien en base (rollback en fin de traitement)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limiter le nombre de lignes (utile pour tester)",
    )
    args = parser.parse_args()
    asyncio.run(importer(excel_path=args.excel, dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
