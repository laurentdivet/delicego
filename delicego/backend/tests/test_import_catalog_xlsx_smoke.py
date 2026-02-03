from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.configuration import parametres_application
from app.domaine.modeles.catalogue import Produit, ProduitFournisseur
from app.domaine.modeles.referentiel import Fournisseur
from scripts import seed_all
from scripts import import_catalog_xlsx


@pytest.mark.asyncio
async def test_import_catalog_xlsx_is_idempotent_and_writes_reports(tmp_path: Path, session_test: AsyncSession) -> None:
    """Smoke:
    - DB neuve
    - seed_all --apply
    - import_catalog_xlsx --apply sur fixture
    - assertions: compteurs augmentent, reports créés, pas de doublons au second import
    """

    # IMPORTANT: le script import_catalog_xlsx refuse une DB implicite.
    os.environ["DATABASE_URL"] = parametres_application.url_base_donnees

    # Seed baseline
    await seed_all.seed_all(apply=True, catalog_xlsx=None, subset=None)

    async def counts(session: AsyncSession) -> tuple[int, int, int]:
        n_f = int((await session.execute(select(func.count()).select_from(Fournisseur))).scalar_one())
        n_p = int((await session.execute(select(func.count()).select_from(Produit))).scalar_one())
        n_pf = int((await session.execute(select(func.count()).select_from(ProduitFournisseur))).scalar_one())
        return n_f, n_p, n_pf

    before = await counts(session_test)

    fixture_xlsx = Path(__file__).with_name("fixtures") / "catalog_min.xlsx"
    assert fixture_xlsx.exists()

    reports_dir = tmp_path / "reports"

    rc1 = await import_catalog_xlsx.run(
        xlsx_path=str(fixture_xlsx),
        apply=True,
        reports_dir=reports_dir,
        fuzzy_threshold=None,  # deterministe
    )
    assert rc1 == 0

    after1 = await counts(session_test)
    assert after1[0] >= before[0] + 1  # fournisseur TestSupplier
    # Le seed crée déjà ces 2 produits (catalogue mini). L'import peut donc:
    # - soit les retrouver (produits_created=0)
    # - soit en créer de nouveaux selon fixture/seed
    # On garantit au minimum l'ajout des lignes produit_fournisseur.
    assert after1[1] >= before[1]
    assert after1[2] >= before[2] + 2  # 2 produit_fournisseur

    # Reports: dossier daté + 3 fichiers minimum
    assert reports_dir.exists()
    subdirs = [p for p in reports_dir.iterdir() if p.is_dir()]
    assert subdirs, "un sous-dossier daté doit être créé"
    latest = sorted(subdirs)[-1]
    assert (latest / "ingredient_alias_load_report.csv").exists()
    assert (latest / "ingredient_unmapped_summary.csv").exists()
    assert (latest / "ingredients_non_mappes.csv").exists()

    # Re-import => idempotent (pas d'augmentation)
    rc2 = await import_catalog_xlsx.run(
        xlsx_path=str(fixture_xlsx),
        apply=True,
        reports_dir=reports_dir,
        fuzzy_threshold=None,
    )
    assert rc2 == 0

    after2 = await counts(session_test)
    assert after2 == after1
