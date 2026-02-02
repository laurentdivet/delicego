from __future__ import annotations

"""Import catalogue fournisseur Foodex (XLSX).

Le PDF est utile pour lecture humaine, mais en pratique l'import fiable se fait
à partir du fichier Excel (beaucoup plus simple à parser).

Le fichier Desktop fourni: /Users/lolo/Desktop/CATALOGUE foodex.xlsx

Objectifs:
- Créer/mettre à jour les `Produit` (un produit logique unique par article)
- Créer/mettre à jour les `ProduitFournisseur` correspondants
- Idempotent (rejouable) via contrainte (fournisseur_id, reference_fournisseur)
- Ne PAS créer d'ingrédients.

Exécution (depuis backend/):

    python -m scripts.import_catalogue_foodex_xlsx --xlsx "/Users/lolo/Desktop/CATALOGUE foodex.xlsx" --dry-run
    python -m scripts.import_catalogue_foodex_xlsx --xlsx "/Users/lolo/Desktop/CATALOGUE foodex.xlsx"
"""

import argparse
import asyncio
import os
import re
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.catalogue import Produit, ProduitFournisseur
from app.domaine.modeles.referentiel import Fournisseur


def _norm(s: str) -> str:
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _to_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("€", "").strip()
    s = s.replace("\xa0", " ")
    s = s.replace(" ", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_ref_and_price(cell_value: str) -> tuple[str | None, float | None]:
    """Extrait (reference, prix) depuis une cellule type:
    - "200395/130001            34,90 €"
    - "133190                   89,90 €"

    IMPORTANT: éviter de concaténer le code et le prix.
    """

    code_m = re.search(r"(\d{5,}(?:/\d{5,})?)", cell_value)
    ref = code_m.group(1) if code_m else None

    price_m = re.search(r"(\d+[\.,]\d{2})\s*€", cell_value)
    prix = _to_float(price_m.group(0)) if price_m else None
    return ref, prix


def _extract_longest_text(raw_cell: str) -> str | None:
    """Heuristique pour récupérer un libellé depuis une cellule "mixte".

    Sur certains fichiers (ex: export produits), la cellule peut contenir:
      "3760...  MOZZA RAPE 1KG  12,90 €"

    On retire les tokens numériques longs et le prix, puis on garde le reste.
    """

    s = str(raw_cell).strip()
    if not s:
        return None
    s = re.sub(r"(\d+[\.,]\d{2})\s*€", " ", s)
    s = re.sub(r"\b\d{5,}\b", " ", s)
    s = _norm(s)
    return s or None


def _norm_unite_achat(u: str | None) -> str | None:
    if u is None:
        return None
    s = _norm(u).lower()
    # normalisation simple (on garde volontairement les abréviations en minuscules)
    mapping = {
        "sac": "sac",
        "bidon": "bidon",
        "ct": "ct",
        "carton": "ct",
        "bg": "bg",
        "pce": "pce",
        "pc": "pce",
        "pièce": "pce",
        "piece": "pce",
    }
    return mapping.get(s, s or None)


def _parse_contenance(raw: str | None) -> float | None:
    """Parse une contenance Foodex Clean.

    Exemples:
    - '20KG' -> 20.0
    - '22,68KG' -> 22.68
    - '1KG x 10' -> 1.0 (on ne multiplie pas ici : pas de champ dédié)
    - '20L' -> 20.0

    Si parsing impossible => None.
    """

    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s or s == "NAN":
        return None
    s = s.replace(" ", "")
    s = s.replace(",", ".")
    # prend le premier nombre
    m = re.match(r"^(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


@dataclass
class ImportStats:
    total_lignes_lues: int = 0
    lignes_valides: int = 0
    produits_crees: int = 0
    pf_crees: int = 0
    pf_maj: int = 0
    pf_ignores: int = 0
    ignore_code_manquant: int = 0
    ignore_ref_manquante: int = 0
    ignore_autre: int = 0
    contenance_parse_fail: int = 0


async def importer(
    *,
    xlsx_path: str,
    dry_run: bool,
    fournisseur_nom: str = "Foodex",
    sheet: str | int | None = None,
    limit: int | None = None,
) -> None:
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # 1) On lit d'abord en mode tabulaire (header=0) pour détecter les colonnes.
    # 2) Si pas tabulaire, on retombe sur la lecture "grille" historique (header=None).
    sheet_name = 0 if sheet is None else sheet
    df0 = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=0)
    cols = [str(c).strip() for c in df0.columns.tolist()]
    cols_upper = {c.upper() for c in cols}
    is_foodex_clean = {
        "CODE",
        "RÉFÉRENCE",
        "REFERENCE",
        "UNITÉ DE VENTE",
        "UNITE DE VENTE",
        "PRIX HT",
    }

    # Détection "Foodex Clean": au minimum Code + Référence + Unité de vente + Prix HT
    has_code = "CODE" in cols_upper
    has_ref = ("RÉFÉRENCE" in cols_upper) or ("REFERENCE" in cols_upper)
    has_unite_vente = ("UNITÉ DE VENTE" in cols_upper) or ("UNITE DE VENTE" in cols_upper)
    has_prix_ht = "PRIX HT" in cols_upper
    if has_code and has_ref and has_unite_vente and has_prix_ht:
        df = df0
        mode = "FOODEX_CLEAN"
    else:
        # Fallback: grille historique
        df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None)
        mode = "GRILLE_OR_TABULAIRE_LEGACY"

    async with session_maker() as session:
        resf = await session.execute(select(Fournisseur).where(Fournisseur.nom == fournisseur_nom))
        fournisseur = resf.scalar_one_or_none()
        if fournisseur is None:
            fournisseur = Fournisseur(nom=fournisseur_nom, actif=True)
            session.add(fournisseur)
            await session.flush()

        stats = ImportStats()

        def iter_articles() -> list[tuple[str, str, float | None, str | None, float | None]]:
            """Retourne une liste (ref, libelle, prix_ht).

            IMPORTANT:
            - Le fichier Foodex "grille" a 2 lignes par article (code/prix puis libellé).
            - Mais on supporte aussi des fichiers "produits" où le libellé et/ou l'EAN
              est directement dans la cellule "code/prix" (ex: PRODUITS_SORAE.xlsx).
            """

            # 0) Mode Foodex Clean (tableau)
            if mode == "FOODEX_CLEAN":
                articles: list[tuple[str, str, float | None, str | None, float | None]] = []

                # normalise noms de colonnes
                col_map = {str(c).strip(): c for c in df.columns}

                def get(row, key_variants: list[str]):
                    for k in key_variants:
                        if k in col_map:
                            return row.get(col_map[k])
                    return None

                it = df.iterrows()
                if limit is not None:
                    it = list(it)[:limit]

                for _, row in it:
                    stats.total_lignes_lues += 1
                    code = get(row, ["Code", "CODE"])
                    ref = get(row, ["Référence", "RÉFÉRENCE", "Reference", "REFERENCE"])
                    unite_vente = get(row, ["Unité de vente", "UNITÉ DE VENTE", "Unite de vente", "UNITE DE VENTE"])
                    prix_ht = get(row, ["Prix HT", "PRIX HT"])
                    contenance = get(row, ["Contenance", "CONTENANCE"])

                    ref_code = str(code).strip() if code is not None and not (isinstance(code, float) and pd.isna(code)) else ""
                    libelle = _norm(ref) if ref is not None and str(ref).strip() and not (isinstance(ref, float) and pd.isna(ref)) else ""

                    if not ref_code:
                        stats.pf_ignores += 1
                        stats.ignore_code_manquant += 1
                        continue
                    if not libelle:
                        stats.pf_ignores += 1
                        stats.ignore_ref_manquante += 1
                        continue

                    u = _norm_unite_achat(unite_vente)
                    prix = _to_float(prix_ht)
                    qty = _parse_contenance(contenance)
                    if contenance is not None and qty is None:
                        stats.contenance_parse_fail += 1

                    articles.append((ref_code, libelle, prix, u, qty))

                stats.lignes_valides = len(articles)
                return articles

            # 1) Détection simple d'un header tabulaire (ex: PRODUITS_SORAE.xlsx)
            #    où la 1ère ligne contient "CODE_ARTICLE" et "DESIGNATION".
            first_row = [str(x).strip().upper() for x in df.iloc[0].tolist()]
            if "CODE_ARTICLE" in first_row and "DESIGNATION" in first_row:
                header = [h.strip() for h in df.iloc[0].tolist()]
                dft = df.iloc[1:].copy()
                dft.columns = header
                articles: list[tuple[str, str, float | None, str | None, float | None]] = []

                def get(row, key: str):
                    if key not in dft.columns:
                        return None
                    return row.get(key)

                for _, row in dft.iterrows():
                    code = get(row, "CODE_ARTICLE")
                    lib = get(row, "DESIGNATION")
                    ean = get(row, "EAN13")
                    prix = get(row, "PRIX")

                    ref = str(code).strip() if code is not None and str(code).strip() else None
                    libelle = _norm(lib) if lib is not None and str(lib).strip() else None
                    # ref fallback
                    if not ref and ean is not None and str(ean).strip():
                        ref = str(ean).strip()

                    if not ref or not libelle:
                        continue

                    prix_ht = _to_float(prix) if prix is not None else None
                    articles.append((ref, libelle, prix_ht, None, None))

                stats.lignes_valides = len(articles)
                return articles

            # 2) Fallback historique: grille Foodex
            articles: list[tuple[str, str, float | None, str | None, float | None]] = []
            max_r, max_c = df.shape

            def cell(r: int, c: int):
                try:
                    return df.iat[r, c]
                except Exception:
                    return None

            r = 0
            while r < max_r - 1:
                c = 0
                while c < max_c - 1:
                    v = cell(r, c)
                    # Exemple dans le fichier: "200395/130001            34,90 €" ou "200248                   20,90 €".
                    if isinstance(v, str):
                        ref, prix = _extract_ref_and_price(v)
                    else:
                        ref, prix = None, None

                    if ref:
                        # Le libellé est souvent juste en dessous...
                        lib_raw = cell(r + 1, c)
                        if isinstance(lib_raw, str) and lib_raw.strip():
                            lib = _norm(lib_raw)
                            articles.append((ref, lib, prix, None, None))
                            c += 2
                            continue

                        # ... mais fallback: libellé potentiel dans la même cellule.
                        rest = _extract_longest_text(str(v))
                        if rest:
                            articles.append((ref, rest, prix, None, None))

                        c += 2
                        continue
                    c += 1
                r += 1

            stats.lignes_valides = len(articles)
            return articles

        articles = iter_articles()
        if not articles:
            raise RuntimeError("Aucun article détecté dans le XLSX (format inattendu).")

        for ref, lib, prix, unite_in, qty_in in articles:
            cat = None
            unite = unite_in or "pce"

            # Produit par libellé (source de vérité: article)
            # NB: si lib est un EAN (digits only), on tente de récupérer le libellé fournisseur.
            # Ici on n'a pas cette info => on laisse tel quel.
            res_p = await session.execute(select(Produit).where(Produit.libelle == lib))
            produit = res_p.scalar_one_or_none()
            if produit is None:
                produit = Produit(libelle=lib, categorie=cat, actif=True)
                session.add(produit)
                await session.flush()
                stats.produits_crees += 1
            else:
                if produit.categorie is None and cat:
                    produit.categorie = cat

            res_pf = await session.execute(
                select(ProduitFournisseur).where(
                    ProduitFournisseur.fournisseur_id == fournisseur.id,
                    ProduitFournisseur.reference_fournisseur == ref,
                )
            )
            pf = res_pf.scalar_one_or_none()

            qty = qty_in if qty_in is not None else 1.0

            if pf is None:
                pf = ProduitFournisseur(
                    produit_id=produit.id,
                    fournisseur_id=fournisseur.id,
                    reference_fournisseur=ref,
                    libelle_fournisseur=lib,
                    unite_achat=unite or "pce",
                    quantite_par_unite=qty,
                    prix_achat_ht=prix,
                    tva=None,
                    actif=True,
                )
                session.add(pf)
                stats.pf_crees += 1
            else:
                pf.produit_id = produit.id
                pf.libelle_fournisseur = lib
                pf.unite_achat = unite or pf.unite_achat
                pf.quantite_par_unite = qty
                pf.prix_achat_ht = prix
                pf.actif = True
                stats.pf_maj += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

        print(
            "[foodex_xlsx] "
            f"mode={mode} lignes_lues={stats.total_lignes_lues} lignes_valides={stats.lignes_valides} "
            f"produits_crees={stats.produits_crees} pf_crees={stats.pf_crees} pf_maj={stats.pf_maj} "
            f"pf_ignores={stats.pf_ignores} (code_manquant={stats.ignore_code_manquant} ref_manquante={stats.ignore_ref_manquante} autre={stats.ignore_autre}) "
            f"contenance_parse_fail={stats.contenance_parse_fail} dry_run={dry_run}"
        )

    await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import catalogue Foodex depuis XLSX")
    p.add_argument("--xlsx", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fournisseur-nom", default="Foodex")
    p.add_argument("--sheet", default=None, help="Nom ou index de feuille (défaut: première)")
    p.add_argument("--limit", type=int, default=None, help="Limiter à N lignes (debug)")
    return p


def main() -> None:
    args = build_parser().parse_args()
    sheet = args.sheet
    if isinstance(sheet, str) and sheet.strip().isdigit():
        sheet = int(sheet.strip())
    asyncio.run(
        importer(
            xlsx_path=args.xlsx,
            dry_run=args.dry_run,
            fournisseur_nom=args.fournisseur_nom,
            sheet=sheet,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
