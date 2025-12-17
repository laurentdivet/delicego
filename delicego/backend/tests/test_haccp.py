from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import (
    TypeEquipementThermique,
    TypeMagasin,
    TypeMouvementStock,
    ZoneEquipementThermique,
)
from app.domaine.modeles.hygiene import EquipementThermique, ReleveTemperature
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, Magasin
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.domaine.services.haccp import ServiceHACCP


@pytest.mark.asyncio
async def test_temperature_hors_seuil_detectee(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session_test.add(magasin)
    await session_test.flush()

    eq = EquipementThermique(
        magasin_id=magasin.id,
        nom="Frigo",
        actif=True,
        type_equipement=TypeEquipementThermique.FRIGO,
        zone=ZoneEquipementThermique.PRODUCTION,
        temperature_min=0.0,
        temperature_max=4.0,
    )
    session_test.add(eq)
    await session_test.flush()

    # relevé à 8°C -> hors seuil
    session_test.add(
        ReleveTemperature(
            equipement_thermique_id=eq.id,
            releve_le=datetime.now(timezone.utc),
            temperature=8.0,
            commentaire=None,
        )
    )

    await session_test.commit()

    service = ServiceHACCP(session_test)
    anomalies = await service.verifier_temperature()
    assert len(anomalies) == 1
    assert anomalies[0].equipement_id == eq.id


@pytest.mark.asyncio
async def test_dlc_depassee_detectee(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fresh", actif=True)
    ingredient = Ingredient(nom="Saumon", unite_stock="kg", unite_mesure="kg", actif=True)
    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    lot = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="S1",
        date_dlc=date.today() - timedelta(days=1),
        unite="kg",
    )
    session_test.add(lot)
    await session_test.commit()

    # stock restant > 0
    session_test.add(
        MouvementStock(
            type_mouvement=TypeMouvementStock.RECEPTION,
            horodatage=datetime.now(timezone.utc),
            magasin_id=magasin.id,
            ingredient_id=ingredient.id,
            lot_id=lot.id,
            quantite=1.0,
            unite="kg",
        )
    )
    await session_test.commit()

    service = ServiceHACCP(session_test)
    anomalies = await service.verifier_dlc(aujourd_hui=date.today())
    assert len(anomalies) == 1
    assert anomalies[0].lot_id == lot.id


@pytest.mark.asyncio
async def test_aucune_anomalie(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    session_test.add(magasin)
    await session_test.flush()

    eq = EquipementThermique(
        magasin_id=magasin.id,
        nom="Frigo",
        actif=True,
        type_equipement=TypeEquipementThermique.FRIGO,
        zone=ZoneEquipementThermique.PRODUCTION,
        temperature_min=0.0,
        temperature_max=4.0,
    )
    session_test.add(eq)
    await session_test.flush()

    # relevé dans la plage
    session_test.add(
        ReleveTemperature(
            equipement_thermique_id=eq.id,
            releve_le=datetime.now(timezone.utc),
            temperature=3.0,
            commentaire=None,
        )
    )

    await session_test.commit()

    service = ServiceHACCP(session_test)
    anomalies_temp = await service.verifier_temperature()
    anomalies_dlc = await service.verifier_dlc(aujourd_hui=date.today())

    assert anomalies_temp == []
    assert anomalies_dlc == []
