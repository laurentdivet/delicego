from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin
from app.domaine.modeles.catalogue import Produit
from app.domaine.modeles.referentiel import Ingredient, Magasin
from app.domaine.modeles.stock_tracabilite import Lot


@pytest.mark.asyncio
async def test_backfill_produit_id_stock_remplit_lot(session_test: AsyncSession) -> None:
    p = Produit(libelle="PROD TEST", categorie=None, actif=True)
    ing = Ingredient(nom="ING TEST", unite_stock="kg", actif=True, produit=p)
    magasin = Magasin(nom="MAG", type_magasin=TypeMagasin.VENTE, actif=True)

    session_test.add_all([p, ing, magasin])
    await session_test.commit()

    lot = Lot(magasin_id=magasin.id, ingredient_id=ing.id, fournisseur_id=None, code_lot=None, date_dlc=None, unite="kg")
    session_test.add(lot)
    await session_test.commit()

    # exécuter la logique de backfill dans la même DB de test
    from scripts.backfill_produit_id_stock import _backfill_table

    cand, bf, imp = await _backfill_table(session=session_test, table="lot", force=False)
    assert cand == 1
    assert bf == 1
    assert imp == 0

    await session_test.commit()

    await session_test.refresh(lot)
    assert getattr(lot, "produit_id") == p.id
