from __future__ import annotations

from datetime import date

import pytest
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeFournisseur, TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin
from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
from app.domaine.modeles.comptabilite import EcritureComptable
from app.domaine.modeles.stock_tracabilite import MouvementStock

from app.domaine.services.commander_fournisseur import (
    DonneesInvalidesCommandeFournisseur,
    ServiceCommandeFournisseur,
)
from app.domaine.services.generer_besoins_fournisseurs import ServiceGenerationBesoinsFournisseurs
from app.main import creer_application
from tests._http_helpers import entetes_internes


def _app_avec_dependances_test(session_test: AsyncSession):
    app = creer_application()

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    from app.api.dependances import fournir_session

    async def _fournir_session_override():
        assert session_test.bind is not None
        async with _AsyncSession(bind=session_test.bind, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[fournir_session] = _fournir_session_override
    return app


async def _client_api(session_test: AsyncSession) -> httpx.AsyncClient:
    app = _app_avec_dependances_test(session_test)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _entetes_internes() -> dict[str, str]:
    return entetes_internes()


@pytest.mark.asyncio
async def test_creation_commande_fournisseur_brouillon_sans_stock(session_test: AsyncSession) -> None:
    fournisseur = Fournisseur(nom="Fournisseur A", actif=True)
    ingredient = Ingredient(nom="Farine", unite_stock="kg", unite_consommation="kg", cout_unitaire=2.5, actif=True)
    session_test.add_all([fournisseur, ingredient])
    await session_test.commit()

    service = ServiceCommandeFournisseur(session_test)

    commande_id = await service.creer_commande(fournisseur_id=fournisseur.id, commentaire="test")
    await service.ajouter_ligne(
        commande_fournisseur_id=commande_id,
        ingredient_id=ingredient.id,
        quantite=10.0,
        unite="kg",
    )

    # commande en BROUILLON
    res = await session_test.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == commande_id))
    commande = res.scalar_one()
    assert commande.statut == StatutCommandeFournisseur.BROUILLON

    # aucun stock avant réception
    res_ms = await session_test.execute(select(MouvementStock))
    assert list(res_ms.scalars().all()) == []


@pytest.mark.asyncio
async def test_reception_partielle_statut_partielle_et_stock_sur_recu(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fournisseur B", actif=True)
    ingredient = Ingredient(nom="Tomate", unite_stock="kg", unite_consommation="kg", cout_unitaire=3.0, actif=True)
    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    service = ServiceCommandeFournisseur(session_test)
    commande_id = await service.creer_commande(fournisseur_id=fournisseur.id)
    await service.ajouter_ligne(
        commande_fournisseur_id=commande_id,
        ingredient_id=ingredient.id,
        quantite=2.0,
        unite="kg",
    )
    await service.envoyer_commande(commande_fournisseur_id=commande_id)

    # réception partielle : 0.5kg
    await service.receptionner_commande(
        commande_fournisseur_id=commande_id,
        magasin_id=magasin.id,
        lignes_reception=[(ingredient.id, 0.5, "kg")],
        reference_externe="BL-1",
    )

    # statut PARTIELLE
    res = await session_test.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == commande_id))
    commande = res.scalar_one()
    assert commande.statut == StatutCommandeFournisseur.PARTIELLE

    # ligne : quantite_recue mise à jour
    res_ligne = await session_test.execute(
        select(LigneCommandeFournisseur).where(LigneCommandeFournisseur.commande_fournisseur_id == commande_id)
    )
    ligne = res_ligne.scalar_one()
    assert ligne.quantite == pytest.approx(2.0)
    assert ligne.quantite_recue == pytest.approx(0.5)

    # mouvements stock : uniquement sur reçu
    res_ms = await session_test.execute(select(MouvementStock))
    mouvements = list(res_ms.scalars().all())
    assert len(mouvements) == 1
    assert mouvements[0].type_mouvement == TypeMouvementStock.RECEPTION
    assert mouvements[0].quantite == pytest.approx(0.5)

    # écritures comptables : une paire 607/44566 pour la réception (suffixe ":1")
    res_ec = await session_test.execute(
        select(EcritureComptable).where(EcritureComptable.reference_interne.like(f"{commande_id}:%"))
    )
    ecritures = list(res_ec.scalars().all())
    comptes = sorted([e.compte_comptable for e in ecritures])
    assert comptes == ["44566", "607"]


@pytest.mark.asyncio
async def test_reception_complete_apres_partielle_cumul_et_statut_receptionnee(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fournisseur B2", actif=True)
    ingredient = Ingredient(nom="Tomate", unite_stock="kg", unite_consommation="kg", cout_unitaire=3.0, actif=True)
    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    service = ServiceCommandeFournisseur(session_test)
    commande_id = await service.creer_commande(fournisseur_id=fournisseur.id)
    await service.ajouter_ligne(commande_fournisseur_id=commande_id, ingredient_id=ingredient.id, quantite=2.0, unite="kg")
    await service.envoyer_commande(commande_fournisseur_id=commande_id)

    # partielle : 0.5
    await service.receptionner_commande(
        commande_fournisseur_id=commande_id,
        magasin_id=magasin.id,
        lignes_reception=[(ingredient.id, 0.5, "kg")],
        reference_externe="BL-1",
    )

    # complète : réception du reliquat via appel par défaut (lignes_reception=None)
    await service.receptionner_commande(
        commande_fournisseur_id=commande_id,
        magasin_id=magasin.id,
        reference_externe="BL-2",
    )

    res = await session_test.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == commande_id))
    commande = res.scalar_one()
    assert commande.statut == StatutCommandeFournisseur.RECEPTIONNEE

    res_ligne = await session_test.execute(
        select(LigneCommandeFournisseur).where(LigneCommandeFournisseur.commande_fournisseur_id == commande_id)
    )
    ligne = res_ligne.scalar_one()
    assert ligne.quantite_recue == pytest.approx(2.0)

    # mouvements stock : 2 (0.5 puis 1.5)
    res_ms = await session_test.execute(select(MouvementStock))
    mouvements = list(res_ms.scalars().all())
    assert len(mouvements) == 2
    assert sorted([float(m.quantite) for m in mouvements]) == [pytest.approx(0.5), pytest.approx(1.5)]

    # écritures comptables : 2 réceptions => 4 écritures
    res_ec = await session_test.execute(
        select(EcritureComptable).where(EcritureComptable.reference_interne.like(f"{commande_id}:%"))
    )
    ecritures = list(res_ec.scalars().all())
    assert len(ecritures) == 4


@pytest.mark.asyncio
async def test_rollback_si_erreur_pendant_reception(session_test: AsyncSession) -> None:
    magasin = Magasin(nom="Escat2", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fournisseur C", actif=True)
    ingredient = Ingredient(nom="Beurre", unite_stock="kg", unite_consommation="kg", cout_unitaire=5.0, actif=True)
    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    service = ServiceCommandeFournisseur(session_test)
    commande_id = await service.creer_commande(fournisseur_id=fournisseur.id)
    await service.ajouter_ligne(commande_fournisseur_id=commande_id, ingredient_id=ingredient.id, quantite=1.0, unite="kg")
    await service.envoyer_commande(commande_fournisseur_id=commande_id)

    # forcer une erreur APRES début de transaction dédiée : quantite > reliquat
    with pytest.raises(DonneesInvalidesCommandeFournisseur):
        await service.receptionner_commande(
            commande_fournisseur_id=commande_id,
            magasin_id=magasin.id,
            lignes_reception=[(ingredient.id, 999.0, "kg")],
        )

    # rien ne doit avoir été écrit
    res_ms = await session_test.execute(select(MouvementStock))
    assert list(res_ms.scalars().all()) == []

    res_ec = await session_test.execute(select(EcritureComptable))
    assert list(res_ec.scalars().all()) == []

    # quantite_recue doit rester à 0
    res_ligne = await session_test.execute(
        select(LigneCommandeFournisseur).where(LigneCommandeFournisseur.commande_fournisseur_id == commande_id)
    )
    ligne = res_ligne.scalar_one()
    assert ligne.quantite_recue == pytest.approx(0.0)

    res = await session_test.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == commande_id))
    commande = res.scalar_one()
    assert commande.statut == StatutCommandeFournisseur.ENVOYEE


@pytest.mark.asyncio
async def test_generation_besoins_cree_commande_brouillon_sans_stock(session_test: AsyncSession) -> None:
    # prérequis : magasin + fournisseur + ingredient
    magasin = Magasin(nom="Mag Besoins", type_magasin=TypeMagasin.VENTE, actif=True)
    fournisseur = Fournisseur(nom="AAA Fournisseur", actif=True)
    ingredient = Ingredient(nom="Sel", unite_stock="kg", unite_consommation="kg", cout_unitaire=1.0, actif=True)
    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    # Créer un plan de production avec une recette + BOM pour générer un besoin
    from app.domaine.modeles.referentiel import Menu, Recette, LigneRecette
    from app.domaine.modeles.production import PlanProduction, LignePlanProduction

    recette = Recette(nom="Recette")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    session_test.add(LigneRecette(recette_id=recette.id, ingredient_id=ingredient.id, quantite=2.0, unite="kg"))
    await session_test.commit()

    plan = PlanProduction(magasin_id=magasin.id, date_plan=date(2025, 1, 1))
    session_test.add(plan)
    await session_test.commit()

    session_test.add(LignePlanProduction(plan_production_id=plan.id, recette_id=recette.id, quantite_a_produire=3.0))
    await session_test.commit()

    service = ServiceGenerationBesoinsFournisseurs(session_test)
    ids = await service.generer(magasin_id=magasin.id, date_cible=date(2025, 1, 1), horizon=1)

    assert len(ids) == 1

    res_cmd = await session_test.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == ids[0]))
    cmd = res_cmd.scalar_one()
    assert cmd.statut == StatutCommandeFournisseur.BROUILLON

    res_lignes = await session_test.execute(
        select(LigneCommandeFournisseur).where(LigneCommandeFournisseur.commande_fournisseur_id == cmd.id)
    )
    lignes = list(res_lignes.scalars().all())
    assert len(lignes) == 1
    assert lignes[0].ingredient_id == ingredient.id
    assert lignes[0].quantite == pytest.approx(6.0)  # 3 * 2

    # aucun stock
    res_ms = await session_test.execute(select(MouvementStock))
    assert list(res_ms.scalars().all()) == []


@pytest.mark.asyncio
async def test_api_interne_achats_protegee_par_header(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    # Sans header => 401
    reponse = await client.post("/api/interne/achats/commandes", json={})
    assert reponse.status_code == 401

    await client.aclose()
