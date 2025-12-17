from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeClient, TypeEcritureComptable, TypeMagasin
from app.domaine.modeles import Fournisseur, Magasin, Menu
from app.domaine.modeles.achats import CommandeAchat
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.comptabilite import EcritureComptable
from app.domaine.modeles.referentiel import Recette
from app.main import creer_application


def _client_interne() -> TestClient:
    return TestClient(creer_application())


def _entetes_internes() -> dict[str, str]:
    return {"X-CLE-INTERNE": "cle-technique"}


@pytest.mark.asyncio
async def test_comptabilite_aucune_ecriture_si_aucune_donnee(session_test: AsyncSession) -> None:
    client = _client_interne()

    r = client.post(
        "/api/interne/comptabilite/generer",
        headers=_entetes_internes(),
        json={"date_debut": "2025-01-01", "date_fin": "2025-01-31"},
    )
    assert r.status_code == 201
    assert r.json()["nombre_ecritures"] == 0


@pytest.mark.asyncio
async def test_comptabilite_generation_ecritures_ventes(session_test: AsyncSession) -> None:
    client = _client_interne()

    magasin = Magasin(nom="Magasin Compta", type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add(magasin)
    await session_test.commit()

    recette = Recette(nom="Recette Compta")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Compta", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    commande = CommandeClient(
        magasin_id=magasin.id,
        date_commande=datetime(2025, 1, 10, 12, 0, 0, tzinfo=timezone.utc),
        statut=StatutCommandeClient.CONFIRMEE,
    )
    session_test.add(commande)
    await session_test.commit()

    session_test.add(
        LigneCommandeClient(
            commande_client_id=commande.id,
            menu_id=menu.id,
            quantite=2.0,
            lot_production_id=None,
        )
    )
    await session_test.commit()

    r = client.post(
        "/api/interne/comptabilite/generer",
        headers=_entetes_internes(),
        json={"date_debut": "2025-01-01", "date_fin": "2025-01-31"},
    )
    assert r.status_code == 201
    assert r.json()["nombre_ecritures"] == 2  # 706 + 44571

    res = await session_test.execute(select(EcritureComptable).where(EcritureComptable.type == TypeEcritureComptable.VENTE))
    ecritures = list(res.scalars().all())
    assert len(ecritures) == 2
    assert {e.compte_comptable for e in ecritures} == {"706", "44571"}


@pytest.mark.asyncio
async def test_comptabilite_generation_ecritures_achats(session_test: AsyncSession) -> None:
    client = _client_interne()

    magasin = Magasin(nom="Magasin Achat", type_magasin=TypeMagasin.VENTE, actif=True)
    fournisseur = Fournisseur(nom="Fournisseur Achat", actif=True)
    session_test.add_all([magasin, fournisseur])
    await session_test.commit()

    achat = CommandeAchat(
        magasin_id=magasin.id,
        fournisseur_id=fournisseur.id,
        reference="REF-001",
        creee_le=datetime(2025, 1, 15, 9, 0, 0, tzinfo=timezone.utc),
    )
    session_test.add(achat)
    await session_test.commit()

    r = client.post(
        "/api/interne/comptabilite/generer",
        headers=_entetes_internes(),
        json={"date_debut": "2025-01-01", "date_fin": "2025-01-31"},
    )
    assert r.status_code == 201
    assert r.json()["nombre_ecritures"] == 2  # 607 + 44566

    res = await session_test.execute(select(EcritureComptable).where(EcritureComptable.type == TypeEcritureComptable.ACHAT))
    ecritures = list(res.scalars().all())
    assert len(ecritures) == 2
    assert {e.compte_comptable for e in ecritures} == {"607", "44566"}


@pytest.mark.asyncio
async def test_comptabilite_pas_de_doublon_si_deja_genere(session_test: AsyncSession) -> None:
    client = _client_interne()

    magasin = Magasin(nom="Magasin Idem", type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add(magasin)
    await session_test.commit()

    recette = Recette(nom="Recette Idem")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Idem", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    commande = CommandeClient(
        magasin_id=magasin.id,
        date_commande=datetime(2025, 1, 20, 12, 0, 0, tzinfo=timezone.utc),
        statut=StatutCommandeClient.CONFIRMEE,
    )
    session_test.add(commande)
    await session_test.commit()

    session_test.add(
        LigneCommandeClient(
            commande_client_id=commande.id,
            menu_id=menu.id,
            quantite=1.0,
            lot_production_id=None,
        )
    )
    await session_test.commit()

    # Première génération
    r1 = client.post(
        "/api/interne/comptabilite/generer",
        headers=_entetes_internes(),
        json={"date_debut": "2025-01-01", "date_fin": "2025-01-31"},
    )
    assert r1.status_code == 201
    assert r1.json()["nombre_ecritures"] == 2

    # Deuxième génération (même période) -> pas de doublon d’écritures
    r2 = client.post(
        "/api/interne/comptabilite/generer",
        headers=_entetes_internes(),
        json={"date_debut": "2025-01-01", "date_fin": "2025-01-31"},
    )
    assert r2.status_code == 201
    assert r2.json()["nombre_ecritures"] == 0

    res = await session_test.execute(select(EcritureComptable))
    assert len(list(res.scalars().all())) == 2
