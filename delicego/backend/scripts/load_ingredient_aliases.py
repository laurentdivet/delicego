from __future__ import annotations

"""Charge en masse des alias d'ingrédients depuis un CSV.

Objectif:
- upsert déterministe dans `ingredient_alias` sur `alias_normalise` (unique)
- ne jamais créer d'ingrédient

Usage:
    python -m scripts.load_ingredient_aliases --csv ./scripts/exemple_ingredient_aliases.csv --dry-run
    python -m scripts.load_ingredient_aliases --csv ./scripts/exemple_ingredient_aliases.csv --apply
    python -m scripts.load_ingredient_aliases --csv ./scripts/exemple_ingredient_aliases.csv --apply --force

Après import d'alias, vous pouvez lancer un rattrapage:
    # voir app.domaine.services.remap_lignes_recette_importees.remap_lignes_recette_importees
"""

import argparse
import asyncio
import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.referentiel import Ingredient, IngredientAlias
from app.domaine.services.ingredient_matching import normalize_ingredient_label


REPORT_PATH = Path(__file__).with_name("ingredient_alias_load_report.csv")


@dataclass(frozen=True)
class CsvRow:
    row_number: int
    alias: str
    ingredient_id: UUID
    actif: bool
    source: str
    commentaire: str


@dataclass
class RunStats:
    lignes_total: int = 0
    inserts: int = 0
    updates: int = 0
    inchangees: int = 0
    erreurs: int = 0
    conflits: int = 0
    doublons_csv: int = 0


@dataclass(frozen=True)
class ReportRow:
    row_number: int
    alias: str
    alias_normalise: str
    ingredient_id: str
    existing_ingredient_id: str
    action: str
    message: str
    force_applied: str
    actif_final: str
    source_final: str


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    v = raw.strip().lower()
    if v in {"1", "true", "t", "yes", "y"}:
        return True
    if v in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError(f"bool invalide: {raw!r}")


def _sniff_delimiter(sample: str) -> str:
    # auto très simple: on privilégie ';' si présent, sinon ','
    return ";" if ";" in sample and "," not in sample else ","


def _parse_csv(path: Path, *, delimiter: str | None) -> tuple[list[CsvRow], list[tuple[int, str, str, str]]]:
    """Retourne (rows_valides, erreurs).

    erreurs: (row_number, alias, ingredient_id, message)
    """

    rows: list[CsvRow] = []
    errors: list[tuple[int, str, str, str]] = []

    # utf-8-sig: support BOM
    raw_text = path.read_text(encoding="utf-8-sig")
    if not raw_text.strip():
        return [], []

    sniffed = delimiter or _sniff_delimiter(raw_text[:2048])
    f = raw_text.splitlines(True)
    reader = csv.DictReader(f, delimiter=sniffed)

    if reader.fieldnames is None:
        raise RuntimeError("CSV sans en-têtes")

    for i, raw in enumerate(reader, start=2):
        alias = (raw.get("alias") or "").strip()
        ingredient_id_raw = (raw.get("ingredient_id") or "").strip()
        actif_raw = raw.get("actif")
        source = (raw.get("source") or "manual_csv").strip() or "manual_csv"
        commentaire = (raw.get("commentaire") or "").strip()

        if not alias and not ingredient_id_raw and not any((raw.get(k) or "").strip() for k in raw.keys()):
            # ligne vide
            continue

        if not alias:
            errors.append((i, alias, ingredient_id_raw, "alias manquant"))
            continue
        if not ingredient_id_raw:
            errors.append((i, alias, ingredient_id_raw, "ingredient_id manquant"))
            continue
        try:
            ingredient_id = UUID(ingredient_id_raw)
        except Exception:
            errors.append((i, alias, ingredient_id_raw, "ingredient_id n'est pas un UUID"))
            continue

        try:
            actif = _parse_bool(actif_raw, default=True)
        except Exception as e:
            errors.append((i, alias, ingredient_id_raw, f"actif invalide: {e}"))
            continue

        rows.append(
            CsvRow(
                row_number=i,
                alias=alias,
                ingredient_id=ingredient_id,
                actif=actif,
                source=source,
                commentaire=commentaire,
            )
        )

    return rows, errors


async def _ingredient_exists(session: AsyncSession, ingredient_id: UUID) -> bool:
    res = await session.execute(select(Ingredient.id).where(Ingredient.id == ingredient_id))
    return res.scalar_one_or_none() is not None


async def _get_existing_alias(session: AsyncSession, alias_normalise: str) -> IngredientAlias | None:
    res = await session.execute(select(IngredientAlias).where(IngredientAlias.alias_normalise == alias_normalise))
    return res.scalar_one_or_none()


async def run(*, csv_path: Path, apply: bool, force: bool, delimiter: str | None) -> int:
    rows, parse_errors = _parse_csv(csv_path, delimiter=delimiter)

    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    stats = RunStats(lignes_total=len(rows) + len(parse_errors))
    report_rows: list[ReportRow] = []

    now = datetime.now(timezone.utc)

    async with Session() as session:
        tx = await session.begin()
        try:
            # erreurs de parsing
            for row_number, alias, ingredient_id_raw, msg in parse_errors:
                stats.erreurs += 1
                report_rows.append(
                    ReportRow(
                        row_number=row_number,
                        alias=alias,
                        alias_normalise=normalize_ingredient_label(alias),
                        ingredient_id=ingredient_id_raw,
                        existing_ingredient_id="",
                        action="error",
                        message=msg,
                        force_applied="false",
                        actif_final="",
                        source_final="",
                    )
                )

            seen_norm: dict[str, int] = {}

            for r in rows:
                alias_normalise = normalize_ingredient_label(r.alias)
                if not alias_normalise:
                    stats.erreurs += 1
                    report_rows.append(
                        ReportRow(
                            row_number=r.row_number,
                            alias=r.alias,
                            alias_normalise=alias_normalise,
                            ingredient_id=str(r.ingredient_id),
                            existing_ingredient_id="",
                            action="error",
                            message="alias_normalise vide",
                            force_applied="false",
                            actif_final="",
                            source_final="",
                        )
                    )
                    continue

                if alias_normalise in seen_norm:
                    stats.doublons_csv += 1
                    stats.erreurs += 1
                    report_rows.append(
                        ReportRow(
                            row_number=r.row_number,
                            alias=r.alias,
                            alias_normalise=alias_normalise,
                            ingredient_id=str(r.ingredient_id),
                            existing_ingredient_id="",
                            action="error",
                            message=f"doublon CSV: alias_normalise déjà vu ligne {seen_norm[alias_normalise]}",
                            force_applied="false",
                            actif_final=str(r.actif).lower(),
                            source_final=r.source,
                        )
                    )
                    continue
                seen_norm[alias_normalise] = r.row_number

                if not await _ingredient_exists(session, r.ingredient_id):
                    stats.erreurs += 1
                    report_rows.append(
                        ReportRow(
                            row_number=r.row_number,
                            alias=r.alias,
                            alias_normalise=alias_normalise,
                            ingredient_id=str(r.ingredient_id),
                            existing_ingredient_id="",
                            action="error",
                            message="ingredient_id inexistant en base",
                            force_applied="false",
                            actif_final=str(r.actif).lower(),
                            source_final=r.source,
                        )
                    )
                    continue

                existing = await _get_existing_alias(session, alias_normalise)
                existing_ing = str(existing.ingredient_id) if existing is not None else ""
                force_applied = "true" if (existing is not None and existing.ingredient_id != r.ingredient_id and force) else "false"

                if existing is not None and existing.ingredient_id != r.ingredient_id:
                    stats.conflits += 1
                    if not force:
                        stats.erreurs += 1
                        report_rows.append(
                            ReportRow(
                                row_number=r.row_number,
                                alias=r.alias,
                                alias_normalise=alias_normalise,
                                ingredient_id=str(r.ingredient_id),
                                existing_ingredient_id=existing_ing,
                                action="conflict",
                                message=f"alias_normalise déjà lié à {existing.ingredient_id} (utiliser --force)",
                                force_applied="false",
                                actif_final=str(r.actif).lower(),
                                source_final=r.source,
                            )
                        )
                        continue

                if not apply:
                    if existing is None:
                        stats.inserts += 1
                        action = "insert"
                    elif existing.ingredient_id == r.ingredient_id:
                        stats.updates += 1
                        action = "update"
                    else:
                        stats.updates += 1
                        action = "update_force"

                    report_rows.append(
                        ReportRow(
                            row_number=r.row_number,
                            alias=r.alias,
                            alias_normalise=alias_normalise,
                            ingredient_id=str(r.ingredient_id),
                            existing_ingredient_id=existing_ing,
                            action=action,
                            message="dry-run",
                            force_applied=force_applied,
                            actif_final=str(r.actif).lower(),
                            source_final=r.source,
                        )
                    )
                    continue

                # apply
                if existing is None:
                    await session.execute(
                        insert(IngredientAlias).values(
                            id=uuid4(),
                            alias=r.alias,
                            alias_normalise=alias_normalise,
                            ingredient_id=r.ingredient_id,
                            source=r.source,
                            actif=bool(r.actif),
                            cree_le=now,
                            mis_a_jour_le=now,
                        )
                    )
                    stats.inserts += 1
                    report_rows.append(
                        ReportRow(
                            row_number=r.row_number,
                            alias=r.alias,
                            alias_normalise=alias_normalise,
                            ingredient_id=str(r.ingredient_id),
                            existing_ingredient_id="",
                            action="insert",
                            message="ok",
                            force_applied="false",
                            actif_final=str(r.actif).lower(),
                            source_final=r.source,
                        )
                    )
                    continue

                await session.execute(
                    insert(IngredientAlias)
                    .values(
                        id=existing.id,
                        alias=r.alias,
                        alias_normalise=alias_normalise,
                        ingredient_id=r.ingredient_id,
                        source=r.source,
                        actif=bool(r.actif),
                        cree_le=existing.cree_le,
                        mis_a_jour_le=now,
                    )
                    .on_conflict_do_update(
                        constraint="uq_ingredient_alias_alias_normalise",
                        set_={
                            "alias": r.alias,
                            "ingredient_id": r.ingredient_id,
                            "source": r.source,
                            "actif": bool(r.actif),
                            "mis_a_jour_le": now,
                        },
                    )
                )

                if existing.ingredient_id == r.ingredient_id and existing.actif == bool(r.actif) and existing.source == r.source:
                    stats.inchangees += 1
                    action = "unchanged"
                else:
                    stats.updates += 1
                    action = "update" if existing.ingredient_id == r.ingredient_id else "update_force"

                report_rows.append(
                    ReportRow(
                        row_number=r.row_number,
                        alias=r.alias,
                        alias_normalise=alias_normalise,
                        ingredient_id=str(r.ingredient_id),
                        existing_ingredient_id=existing_ing,
                        action=action,
                        message="ok",
                        force_applied=force_applied,
                        actif_final=str(r.actif).lower(),
                        source_final=r.source,
                    )
                )

            if apply and stats.erreurs == 0:
                await tx.commit()
            else:
                await tx.rollback()

        except Exception:
            await tx.rollback()
            raise

    await engine.dispose()

    # report CSV
    with REPORT_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "row_number",
                "alias",
                "alias_normalise",
                "ingredient_id",
                "existing_ingredient_id",
                "action",
                "message",
                "force_applied",
                "actif_final",
                "source_final",
            ]
        )
        for rr in report_rows:
            w.writerow(
                [
                    rr.row_number,
                    rr.alias,
                    rr.alias_normalise,
                    rr.ingredient_id,
                    rr.existing_ingredient_id,
                    rr.action,
                    rr.message,
                    rr.force_applied,
                    rr.actif_final,
                    rr.source_final,
                ]
            )

    print("=================== RAPPORT LOAD INGREDIENT_ALIASES ===================")
    print(f"csv                = {csv_path}")
    print(f"mode               = {'apply' if apply else 'dry-run'}")
    print(f"lignes_total        = {stats.lignes_total}")
    print(f"inserts             = {stats.inserts}")
    print(f"updates             = {stats.updates}")
    print(f"inchangées          = {stats.inchangees}")
    print(f"conflits            = {stats.conflits}")
    print(f"doublons_csv        = {stats.doublons_csv}")
    print(f"erreurs             = {stats.erreurs}")
    print(f"report_csv          = {REPORT_PATH}")
    print("=======================================================================")

    return 1 if stats.erreurs else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Charge des alias d'ingrédients depuis un CSV")
    p.add_argument("--csv", required=True, help="Chemin vers le CSV")
    p.add_argument("--force", action="store_true", help="Autorise le changement d'ingredient_id en cas de conflit")
    p.add_argument("--delimiter", choices=[",", ";"], default=None, help="Séparateur CSV (auto par défaut)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    return p


def main() -> None:
    args = build_parser().parse_args()
    apply = bool(args.apply)
    csv_path = Path(args.csv).expanduser()
    asyncio.run(run(csv_path=csv_path, apply=apply, force=bool(args.force), delimiter=args.delimiter))


if __name__ == "__main__":
    main()
