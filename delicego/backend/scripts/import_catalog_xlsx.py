from __future__ import annotations

"""Import générique d'un catalogue fournisseur depuis un XLSX.

Objectifs:
- Importer fournisseurs / produits / produit_fournisseur depuis un XLSX (onglets tolérants)
- Optionnel: extraire une liste d'ingrédients et produire des rapports de mapping
- Idempotent (rejouable sans doublons)
- Dry-run: produire les rapports sans rien écrire en DB
- Apply: transaction atomique (rollback complet sur erreur)

Usage (depuis backend/):

    python -m scripts.import_catalog_xlsx --path ./tests/fixtures/catalog_min.xlsx --dry-run
    python -m scripts.import_catalog_xlsx --path ./tests/fixtures/catalog_min.xlsx --apply

DATABASE:
- DATABASE_URL obligatoire (ou --database-url) comme scripts/run_forecast.py.
"""

import argparse
import asyncio
import csv
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domaine.modeles.catalogue import Produit, ProduitFournisseur
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, IngredientAlias
from app.domaine.services.ingredient_matching import normalize_ingredient_label

# NOTE: insert est importé pour un futur upsert/optimisation (ON CONFLICT) si besoin.
# Dans l'implémentation actuelle, on utilise des SELECT + add/update pour rester simple.


def _display_db_target(database_url: str) -> str:
    p = urlparse(database_url)
    host = p.hostname or "?"
    port = p.port or 5432
    dbname = (p.path or "").lstrip("/") or "?"
    return f"{host}:{port}/{dbname}"


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().split())


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    if not s:
        return None
    s = s.replace("€", "").replace("\xa0", " ")
    s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _first_present(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d:
            return d.get(k)
    return None


def _norm_header(h: str) -> str:
    s = _norm(h).lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _best_sheet_name(sheet_names: list[str], candidates: list[str]) -> str | None:
    if not sheet_names:
        return None
    norm_to_raw = {_norm_header(s): s for s in sheet_names}
    for c in candidates:
        raw = norm_to_raw.get(_norm_header(c))
        if raw:
            return raw
    # fallback fuzzy contains
    for raw in sheet_names:
        n = _norm_header(raw)
        for c in candidates:
            if _norm_header(c) in n:
                return raw
    return None


def _read_sheet(path: str, sheet_name: str) -> pd.DataFrame:
    # Read as table, keep strings where possible.
    return pd.read_excel(path, sheet_name=sheet_name, header=0, dtype=object)


def _map_columns(df: pd.DataFrame) -> dict[str, str]:
    """Tolérant: mappe colonnes brutes -> colonnes canoniques.

    Canonique:
    - fournisseur_nom
    - reference
    - produit_nom
    - libelle_fournisseur
    - unite_achat
    - quantite_par_unite
    - prix_achat_ht
    - ingredient (optionnel)
    """

    cols = {str(c): _norm_header(str(c)) for c in df.columns}

    def pick(*variants: str) -> str | None:
        wanted = {_norm_header(v) for v in variants}
        for raw, normed in cols.items():
            if normed in wanted:
                return raw
        # contains fallback
        for raw, normed in cols.items():
            for v in wanted:
                if v and v in normed:
                    return raw
        return None

    mapping: dict[str, str] = {}
    # fournisseur
    c = pick("fournisseur", "nom fournisseur", "supplier", "vendor")
    if c:
        mapping["fournisseur_nom"] = c
    # référence
    c = pick("reference", "référence", "ref", "sku", "code", "code article", "code_article", "reference fournisseur")
    if c:
        mapping["reference"] = c
    # produit nom
    c = pick("produit", "nom produit", "designation", "désignation", "libellé", "libelle")
    if c:
        mapping["produit_nom"] = c
    # libellé fournisseur
    c = pick("libelle fournisseur", "libellé fournisseur", "libelle_fournisseur", "designation fournisseur")
    if c:
        mapping["libelle_fournisseur"] = c
    # unité
    c = pick("unite", "unité", "unite achat", "unité d'achat", "unite_achat", "unite de vente", "unité de vente")
    if c:
        mapping["unite_achat"] = c
    # quantité
    c = pick("quantite", "quantité", "quantite par unite", "quantité par unité", "quantite_par_unite", "contenance")
    if c:
        mapping["quantite_par_unite"] = c
    # prix
    c = pick("prix", "prix ht", "prix_achat_ht", "prix achat ht")
    if c:
        mapping["prix_achat_ht"] = c
    # ingrédient
    c = pick("ingredient", "ingrédient", "ingredients", "ingrédients")
    if c:
        mapping["ingredient"] = c

    return mapping


@dataclass
class ImportCounts:
    fournisseurs_created: int = 0
    fournisseurs_updated: int = 0
    produits_created: int = 0
    produits_updated: int = 0
    produit_fournisseur_created: int = 0
    produit_fournisseur_updated: int = 0

    ingredients_total_seen: int = 0
    ingredients_mapped: int = 0
    ingredients_unmapped: int = 0


@dataclass(frozen=True)
class AliasLoadRow:
    row_number: int
    alias: str
    alias_normalise: str
    ingredient_id: str
    action: str
    message: str


@dataclass(frozen=True)
class MappingRow:
    source_label: str
    source_normalized: str
    ingredient_id: str
    ingredient_nom: str
    matched_by: str
    score: str
    context: str


def _load_alias_csv(alias_csv: Path) -> tuple[dict[str, UUID], list[AliasLoadRow]]:
    """Charge un CSV alias (offline) et retourne un mapping normalisé -> ingredient_id.

    Format attendu (tolérant): colonnes 'alias' et 'ingredient_id'.
    """

    if not alias_csv.exists():
        return {}, []

    text = alias_csv.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}, []

    # delimiter sniffing minimal
    delim = ";" if ";" in text[:2048] and "," not in text[:2048] else ","
    reader = csv.DictReader(text.splitlines(True), delimiter=delim)
    if reader.fieldnames is None:
        return {}, []

    m: dict[str, UUID] = {}
    report: list[AliasLoadRow] = []
    seen: dict[str, int] = {}

    for i, row in enumerate(reader, start=2):
        alias = _norm(row.get("alias") or row.get("Alias") or "")
        ing_id_raw = _norm(row.get("ingredient_id") or row.get("IngredientId") or row.get("ingredient") or "")

        if not alias and not ing_id_raw and not any(_norm(v) for v in row.values()):
            continue
        if not alias:
            report.append(AliasLoadRow(i, alias, "", ing_id_raw, "error", "alias manquant"))
            continue
        try:
            ing_id = UUID(ing_id_raw)
        except Exception:
            report.append(AliasLoadRow(i, alias, normalize_ingredient_label(alias), ing_id_raw, "error", "ingredient_id invalide"))
            continue

        alias_norm = normalize_ingredient_label(alias)
        if not alias_norm:
            report.append(AliasLoadRow(i, alias, alias_norm, ing_id_raw, "error", "alias_normalise vide"))
            continue

        if alias_norm in seen:
            report.append(AliasLoadRow(i, alias, alias_norm, ing_id_raw, "ignored", f"doublon CSV (déjà vu ligne {seen[alias_norm]})"))
            continue
        seen[alias_norm] = i

        if alias_norm in m and m[alias_norm] != ing_id:
            report.append(AliasLoadRow(i, alias, alias_norm, ing_id_raw, "collision", f"collision: déjà mappé vers {m[alias_norm]}"))
            continue

        m[alias_norm] = ing_id
        report.append(AliasLoadRow(i, alias, alias_norm, ing_id_raw, "loaded", "ok"))

    return m, report


def _similarity(a: str, b: str) -> float:
    """Similarity in [0,1]. Uses rapidfuzz if available, else difflib."""

    try:
        from rapidfuzz import fuzz  # type: ignore

        return float(fuzz.ratio(a, b)) / 100.0
    except Exception:
        import difflib

        return difflib.SequenceMatcher(None, a, b).ratio()


def _match_ingredient(
    *,
    label: str,
    alias_index: dict[str, UUID],
    ingredient_index: dict[str, tuple[UUID, str]],
    ingredient_norms: list[tuple[str, UUID, str]],
    fuzzy_threshold: float | None,
) -> tuple[UUID | None, str | None, str | None, float | None, str]:
    normalized = normalize_ingredient_label(label)
    if not normalized:
        return None, None, None, None, normalized

    # 1) alias CSV
    ing_id = alias_index.get(normalized)
    if ing_id is not None:
        nom = ingredient_index.get(normalized, (ing_id, ""))[1] or None
        return ing_id, nom, "alias_csv", 1.0, normalized

    # 2) alias DB (ingrédient_alias)
    # Note: cette branche est gérée en amont (query DB) en important ingredient_alias en index.
    # Ici on réutilise ingredient_index si alias DB y est injecté via ingredient_norms.

    # 3) exact ingredient.nom normalisé
    exact = ingredient_index.get(normalized)
    if exact is not None:
        return exact[0], exact[1], "exact", 1.0, normalized

    # 4) fuzzy
    if fuzzy_threshold is None:
        return None, None, None, None, normalized

    best: tuple[float, UUID, str] | None = None
    for ing_norm, ing_id2, ing_nom in ingredient_norms:
        score = _similarity(normalized, ing_norm)
        if best is None or score > best[0]:
            best = (score, ing_id2, ing_nom)

    if best is None:
        return None, None, None, None, normalized

    if best[0] >= float(fuzzy_threshold):
        return best[1], best[2], "fuzzy", best[0], normalized

    return None, None, None, best[0], normalized


async def _build_ingredient_indexes(session: AsyncSession) -> tuple[dict[str, tuple[UUID, str]], list[tuple[str, UUID, str]]]:
    res = await session.execute(select(Ingredient.id, Ingredient.nom).where(Ingredient.actif.is_(True)))
    ingredient_index: dict[str, tuple[UUID, str]] = {}
    ingredient_norms: list[tuple[str, UUID, str]] = []
    collisions: set[str] = set()

    for ing_id, nom in res.all():
        key = normalize_ingredient_label(nom)
        if not key:
            continue
        if key in ingredient_index and ingredient_index[key][0] != ing_id:
            collisions.add(key)
            continue
        ingredient_index[key] = (ing_id, str(nom))

    # remove collisions to avoid unsafe exact mapping
    for k in collisions:
        ingredient_index.pop(k, None)

    for k, (ing_id, nom) in ingredient_index.items():
        ingredient_norms.append((k, ing_id, nom))
    return ingredient_index, ingredient_norms


async def _build_alias_db_index(session: AsyncSession) -> dict[str, UUID]:
    res = await session.execute(select(IngredientAlias.alias_normalise, IngredientAlias.ingredient_id).where(IngredientAlias.actif.is_(True)))
    out: dict[str, UUID] = {}
    for alias_norm, ing_id in res.all():
        if not alias_norm:
            continue
        # collisions => ignore
        if alias_norm in out and out[alias_norm] != ing_id:
            out.pop(alias_norm, None)
            continue
        out[alias_norm] = ing_id
    return out


def _make_reports_dir(base_dir: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = base_dir / ts
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_alias_load_report(path: Path, rows: list[AliasLoadRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["row_number", "alias", "alias_normalise", "ingredient_id", "action", "message"])
        for r in rows:
            w.writerow([r.row_number, r.alias, r.alias_normalise, r.ingredient_id, r.action, r.message])


def _write_unmapped_summary(path: Path, unmapped_norm_counts: Counter[str], examples: dict[str, str], limit: int = 100) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ingredient_normalise", "example_brut", "occurences"])
        for ing_norm, n in unmapped_norm_counts.most_common(limit):
            w.writerow([ing_norm, examples.get(ing_norm, ""), n])


def _write_unmapped_full(path: Path, rows: list[MappingRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_label", "source_normalized", "context", "best_score"])
        for r in rows:
            # best_score stored in score even when unmapped
            w.writerow([r.source_label, r.source_normalized, r.context, r.score])


def _write_mapped(path: Path, rows: list[MappingRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_label", "source_normalized", "ingredient_id", "ingredient_nom", "matched_by", "score", "context"])
        for r in rows:
            w.writerow([r.source_label, r.source_normalized, r.ingredient_id, r.ingredient_nom, r.matched_by, r.score, r.context])


async def run(*, xlsx_path: str, apply: bool, reports_dir: Path, fuzzy_threshold: float | None) -> int:
    # DATABASE_URL must be explicit.
    # (same rule as run_forecast)
    # Note: parametres_application.url_base_donnees exists but we don't want implicit target.
    url_db = os.getenv("DATABASE_URL")
    if not url_db:
        # main_async gère déjà le message user-friendly + code 2.
        raise RuntimeError("Missing DATABASE_URL")

    print(f"[import_catalog_xlsx] Using database: {_display_db_target(url_db)}")

    engine = create_async_engine(url_db, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # read workbook to discover sheets
    xl = pd.ExcelFile(xlsx_path)
    sheet_names = list(xl.sheet_names)

    fournisseurs_sheet = _best_sheet_name(sheet_names, ["Fournisseurs", "Fournisseur", "Suppliers"])
    produits_sheet = _best_sheet_name(sheet_names, ["Produits", "Catalogue", "Catalog", "Articles", "ProduitFournisseur", "Produit_Fournisseur"])
    ingredients_sheet = _best_sheet_name(sheet_names, ["Ingrédients", "Ingredients", "Ingredient", "Recette", "Recettes"])

    if not produits_sheet and not fournisseurs_sheet:
        print("[import_catalog_xlsx][ERROR] Aucun onglet Produits/Catalogue ou Fournisseurs détecté.")
        await engine.dispose()
        return 1

    if not fournisseurs_sheet:
        print("[import_catalog_xlsx][WARN] Onglet fournisseurs absent (on utilisera celui indiqué sur chaque ligne produit si présent).")
    if not produits_sheet:
        print("[import_catalog_xlsx][WARN] Onglet produits absent.")
    if not ingredients_sheet:
        print("[import_catalog_xlsx][WARN] Onglet ingrédients/recettes absent (mapping ingrédients basé uniquement sur colonnes 'ingredient' si présentes).")

    df_fournisseurs = _read_sheet(xlsx_path, fournisseurs_sheet) if fournisseurs_sheet else None
    df_produits = _read_sheet(xlsx_path, produits_sheet) if produits_sheet else None
    df_ingredients = _read_sheet(xlsx_path, ingredients_sheet) if ingredients_sheet else None

    counts = ImportCounts()
    reports_out_dir = _make_reports_dir(reports_dir)

    # alias CSV (optional)
    alias_csv = Path(__file__).with_name("ingredient_aliases.csv")
    alias_csv_index, alias_load_report_rows = _load_alias_csv(alias_csv)
    _write_alias_load_report(reports_out_dir / "ingredient_alias_load_report.csv", alias_load_report_rows)

    async with Session() as session:
        tx = await session.begin()
        try:
            # --- indexes for ingredient mapping (read-only)
            ingredient_index, ingredient_norms = await _build_ingredient_indexes(session)
            alias_db_index = await _build_alias_db_index(session)
            # merge alias_db_index on top of alias_csv_index (csv wins for explicit override)
            alias_index = {**alias_db_index, **alias_csv_index}

            # --- 1) fournisseurs (optional sheet)
            fournisseurs_by_name: dict[str, Fournisseur] = {}
            if df_fournisseurs is not None:
                col_map = _map_columns(df_fournisseurs)
                col_nom = col_map.get("fournisseur_nom") or _first_present(
                    {k: k for k in df_fournisseurs.columns},
                    ["Nom", "nom", "Fournisseur", "fournisseur", "Nom fournisseur"],
                )
                if not col_nom:
                    print("[import_catalog_xlsx][WARN] Impossible de détecter la colonne fournisseur dans l'onglet fournisseurs.")
                else:
                    for _, row in df_fournisseurs.iterrows():
                        nom = _norm(row.get(col_nom))
                        if not nom:
                            continue
                        fournisseurs_by_name.setdefault(nom, None)  # placeholder

            # --- 2) produits / produit_fournisseur
            ingredients_seen: list[tuple[str, str]] = []  # (label, context)
            if df_produits is not None:
                col_map = _map_columns(df_produits)
                for _, row in df_produits.iterrows():
                    rowd = {k: row.get(k) for k in df_produits.columns}

                    fournisseur_nom = _norm(_first_present(rowd, [col_map.get("fournisseur_nom", ""), "Fournisseur", "fournisseur", "Nom fournisseur"]))
                    reference = _norm(_first_present(rowd, [col_map.get("reference", ""), "Référence", "Reference", "SKU", "Code"]))
                    produit_nom = _norm(_first_present(rowd, [col_map.get("produit_nom", ""), "Produit", "Nom produit", "Libellé", "Libelle", "Désignation", "Designation"]))
                    libelle_fournisseur = _norm(_first_present(rowd, [col_map.get("libelle_fournisseur", "")])) or produit_nom
                    unite_achat = _norm(_first_present(rowd, [col_map.get("unite_achat", ""), "Unite", "Unité", "Unité de vente", "Unite de vente"])) or "pce"
                    quantite = _to_float(_first_present(rowd, [col_map.get("quantite_par_unite", ""), "Quantité", "Quantite", "Contenance"]))
                    prix_ht = _to_float(_first_present(rowd, [col_map.get("prix_achat_ht", ""), "Prix", "Prix HT", "PRIX HT"]))
                    ing_label = _norm(_first_present(rowd, [col_map.get("ingredient", "")]))

                    if ing_label:
                        ingredients_seen.append((ing_label, f"produit:{produit_nom or libelle_fournisseur}"))

                    if not fournisseur_nom and fournisseurs_by_name:
                        # If missing on row, but fournisseurs sheet exists with single supplier, use it.
                        if len(fournisseurs_by_name) == 1:
                            fournisseur_nom = next(iter(fournisseurs_by_name.keys()))

                    if not fournisseur_nom:
                        # Can't import this row.
                        continue

                    if not produit_nom:
                        continue

                    # -- fournisseur upsert (unique by name)
                    fournisseur = fournisseurs_by_name.get(fournisseur_nom)
                    if fournisseur is None:
                        resf = await session.execute(select(Fournisseur).where(Fournisseur.nom == fournisseur_nom))
                        fournisseur = resf.scalar_one_or_none()
                        if fournisseur is None:
                            if apply:
                                fournisseur = Fournisseur(nom=fournisseur_nom, actif=True)
                                session.add(fournisseur)
                                await session.flush()
                            else:
                                fournisseur = Fournisseur(id=uuid4(), nom=fournisseur_nom, actif=True)  # ephemeral
                            counts.fournisseurs_created += 1
                        else:
                            # ensure active
                            if fournisseur.actif is False and apply:
                                fournisseur.actif = True
                                counts.fournisseurs_updated += 1
                        fournisseurs_by_name[fournisseur_nom] = fournisseur

                    # -- produit upsert (schema actuel: Produit.libelle unique)
                    # NOTE: on suit la contrainte DB existante (unique libelle).
                    # Si un catalogue multi-fournisseurs a des libellés identiques, il faudra
                    # alors faire évoluer le schéma (hors scope ici).
                    res_p = await session.execute(select(Produit).where(Produit.libelle == produit_nom))
                    produit = res_p.scalar_one_or_none()
                    if produit is None:
                        if apply:
                            produit = Produit(libelle=produit_nom, categorie=None, actif=True)
                            session.add(produit)
                            await session.flush()
                        else:
                            produit = Produit(id=uuid4(), libelle=produit_nom, categorie=None, actif=True)  # ephemeral
                        counts.produits_created += 1
                    else:
                        if produit.actif is False and apply:
                            produit.actif = True
                            counts.produits_updated += 1

                    # -- produit_fournisseur upsert (unique by fournisseur_id, reference_fournisseur)
                    if not reference:
                        # Without reference, we can't ensure idempotence for PF rows.
                        # We skip (but product was still imported).
                        continue

                    res_pf = await session.execute(
                        select(ProduitFournisseur).where(
                            ProduitFournisseur.fournisseur_id == fournisseur.id,
                            ProduitFournisseur.reference_fournisseur == reference,
                        )
                    )
                    pf = res_pf.scalar_one_or_none()
                    qty = float(quantite) if quantite is not None else 1.0

                    if pf is None:
                        if apply:
                            pf = ProduitFournisseur(
                                produit_id=produit.id,
                                fournisseur_id=fournisseur.id,
                                reference_fournisseur=reference,
                                libelle_fournisseur=libelle_fournisseur or produit_nom,
                                unite_achat=unite_achat or "pce",
                                quantite_par_unite=qty,
                                prix_achat_ht=prix_ht,
                                tva=None,
                                actif=True,
                            )
                            session.add(pf)
                        counts.produit_fournisseur_created += 1
                    else:
                        # Update fields
                        if apply:
                            pf.produit_id = produit.id
                            pf.libelle_fournisseur = libelle_fournisseur or pf.libelle_fournisseur
                            pf.unite_achat = unite_achat or pf.unite_achat
                            pf.quantite_par_unite = qty
                            pf.prix_achat_ht = prix_ht
                            pf.actif = True
                        counts.produit_fournisseur_updated += 1

            # --- 3) ingrédients sheet optional
            if df_ingredients is not None:
                col_map = _map_columns(df_ingredients)
                ing_col = col_map.get("ingredient")
                if ing_col:
                    for _, row in df_ingredients.iterrows():
                        ing_label = _norm(row.get(ing_col))
                        if ing_label:
                            ingredients_seen.append((ing_label, f"sheet:{ingredients_sheet}"))

            # --- 4) mapping ingredients + reports
            mapped_rows: list[MappingRow] = []
            unmapped_rows: list[MappingRow] = []
            unmapped_counter: Counter[str] = Counter()
            unmapped_examples: dict[str, str] = {}

            for label, ctx in ingredients_seen:
                counts.ingredients_total_seen += 1
                ing_id, ing_nom, method, score, normed = _match_ingredient(
                    label=label,
                    alias_index=alias_index,
                    ingredient_index=ingredient_index,
                    ingredient_norms=ingredient_norms,
                    fuzzy_threshold=fuzzy_threshold,
                )
                if ing_id is not None:
                    counts.ingredients_mapped += 1
                    mapped_rows.append(
                        MappingRow(
                            source_label=label,
                            source_normalized=normed,
                            ingredient_id=str(ing_id),
                            ingredient_nom=ing_nom or "",
                            matched_by=method or "",
                            score=f"{score:.4f}" if score is not None else "",
                            context=ctx,
                        )
                    )
                else:
                    counts.ingredients_unmapped += 1
                    unmapped_rows.append(
                        MappingRow(
                            source_label=label,
                            source_normalized=normed,
                            ingredient_id="",
                            ingredient_nom="",
                            matched_by="",
                            score=f"{score:.4f}" if score is not None else "",
                            context=ctx,
                        )
                    )
                    if normed:
                        unmapped_counter[normed] += 1
                        unmapped_examples.setdefault(normed, label)

            _write_unmapped_summary(
                reports_out_dir / "ingredient_unmapped_summary.csv",
                unmapped_counter,
                unmapped_examples,
            )
            _write_unmapped_full(reports_out_dir / "ingredients_non_mappes.csv", unmapped_rows)
            _write_mapped(reports_out_dir / "ingredient_mapped.csv", mapped_rows)

            if apply:
                await tx.commit()
            else:
                await tx.rollback()

        except Exception:
            await tx.rollback()
            raise
        finally:
            await engine.dispose()

    print("=================== IMPORT CATALOG XLSX ===================")
    print(f"xlsx                 = {xlsx_path}")
    print(f"mode                 = {'apply' if apply else 'dry-run'}")
    print(f"reports_dir          = {reports_out_dir}")
    print(f"fournisseurs_created = {counts.fournisseurs_created}")
    print(f"fournisseurs_updated = {counts.fournisseurs_updated}")
    print(f"produits_created     = {counts.produits_created}")
    print(f"produits_updated     = {counts.produits_updated}")
    print(f"pf_created           = {counts.produit_fournisseur_created}")
    print(f"pf_updated           = {counts.produit_fournisseur_updated}")
    print(f"ingredients_seen     = {counts.ingredients_total_seen}")
    print(f"ingredients_mapped   = {counts.ingredients_mapped}")
    print(f"ingredients_unmapped = {counts.ingredients_unmapped}")
    print("===========================================================")

    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Import catalogue XLSX (générique)")
    p.add_argument("--path", required=True, help="Chemin vers le fichier .xlsx")
    p.add_argument(
        "--reports-dir",
        default=str(Path(__file__).with_name("reports")),
        help="Dossier base pour écrire les rapports (un sous-dossier daté sera créé)",
    )
    p.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.85,
        help="Seuil fuzzy (0..1). Ex: 0.85. Utiliser 0 pour désactiver.",
    )
    p.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override DATABASE_URL (SQLAlchemy async URL)",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    return p.parse_args()


async def main_async() -> int:
    args = _parse_args()
    url_db = args.database_url or os.getenv("DATABASE_URL")
    if not url_db:
        print("[import_catalog_xlsx][ERROR] Missing DATABASE_URL.")
        print("Set env var DATABASE_URL or pass --database-url.")
        print("Example:")
        print("  DATABASE_URL='postgresql+asyncpg://delicego:delicego@localhost:5432/delicego' \\")
        print("  python -m scripts.import_catalog_xlsx --path ./file.xlsx --apply")
        return 2

    # Inject for run() which reads env to avoid accidental implicit target.
    os.environ["DATABASE_URL"] = url_db

    fuzzy = float(args.fuzzy_threshold) if args.fuzzy_threshold is not None else None
    if fuzzy is not None and fuzzy <= 0:
        fuzzy = None

    return await run(
        xlsx_path=str(Path(args.path).expanduser()),
        apply=bool(args.apply),
        reports_dir=Path(args.reports_dir).expanduser(),
        fuzzy_threshold=fuzzy,
    )


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
