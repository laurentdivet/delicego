from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

import pytest
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMagasin, TypeMouvementStock
from app.domaine.modeles import Fournisseur, Ingredient, Magasin, Menu
from app.domaine.modeles.production import LotProduction, PlanProduction
from app.domaine.modeles.referentiel import LigneRecette, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.main import creer_application
from app.core.securite import creer_token_acces


def _entetes_internes_admin(jwt: str) -> dict[str, str]:
    # NOTE: le routeur /api/interne/production exige *à la fois*:
    # - verifier_acces_interne (X-CLE-INTERNE ou Authorization Bearer token interne)
    # - verifier_authentifie (Authorization Bearer jwt)
    # => on ne peut pas utiliser Authorization pour les 2.
    return {
        "X-CLE-INTERNE": "dev-token",
        "Authorization": f"Bearer {jwt}",
    }


def _injecter_jwt_dans_cookie(client: httpx.AsyncClient, jwt: str) -> None:
    """Les dépendances d'auth app lisent parfois le token depuis un cookie."""

    client.cookies.set("token_acces", jwt)


async def _rollback_si_transaction(session: AsyncSession) -> None:
    """Les endpoints utilisent leur propre session DB.

    Dans certains cas, la fixture `session_test` laisse une transaction ouverte,
    ce qui peut provoquer des erreurs côté services (session.begin() imbriqué).
    """

    # propriété sync sur AsyncSession, lecture safe
    if session.sync_session.in_transaction():
        await session.rollback()


def _app_avec_dependances_test(session_test: AsyncSession):
    app = creer_application()

    # IMPORTANT: /api/interne/* vérifie d'abord verifier_acces_interne.
    # Cette dépendance lit la variable d'env INTERNAL_API_TOKEN au moment de l'appel,
    # donc on la force AVANT de commencer à appeler l'API.
    import os

    os.environ["INTERNAL_API_TOKEN"] = "dev-token"

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    # Override DB : nouvelle session liée au même engine que le test
    from app.api.dependances import fournir_session

    async def _fournir_session_override():
        assert session_test.bind is not None
        async with _AsyncSession(bind=session_test.bind, expire_on_commit=False) as s:
            # IMPORTANT:
            # Les services démarrent souvent avec `async with session.begin():`.
            # Avec SQLAlchemy 2, une session peut déjà être en "autobegin" après
            # un premier accès DB. On force donc un rollback ici pour garantir
            # que la transaction démarre au bon endroit.
            if s.sync_session.in_transaction():
                await s.rollback()
            yield s

    app.dependency_overrides[fournir_session] = _fournir_session_override

    return app


async def _client_api(session_test: AsyncSession) -> httpx.AsyncClient:
    app = _app_avec_dependances_test(session_test)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _entetes_internes() -> dict[str, str]:
    # /api/interne/*: accès interne
    return {"X-CLE-INTERNE": "dev-token"}


async def _seed_donnees_planification(session_test: AsyncSession) -> tuple[UUID, date, date]:
    magasin = Magasin(nom="Magasin API", type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add(magasin)
    await session_test.flush()

    recette = Recette(nom="Salade fraiche")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Salade", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    debut = date(2025, 6, 1)
    fin = date(2025, 6, 2)

    from datetime import datetime, timezone

    from app.domaine.enums.types import CanalVente
    from app.domaine.modeles.ventes_prevision import Vente

    session_test.add_all(
        [
            Vente(
                magasin_id=magasin.id,
                menu_id=menu.id,
                date_vente=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
                canal=CanalVente.INTERNE,
                quantite=5.0,
            ),
            Vente(
                magasin_id=magasin.id,
                menu_id=menu.id,
                date_vente=datetime(2025, 6, 2, 12, 0, 0, tzinfo=timezone.utc),
                canal=CanalVente.INTERNE,
                quantite=5.0,
            ),
        ]
    )
    await session_test.commit()

    return magasin.id, debut, fin


async def _creer_user_admin_et_jwt(session_test: AsyncSession) -> str:
    """Crée un user + rôle admin en base et retourne un JWT valide."""

    from app.core.configuration import parametres_application
    from tests._auth_helpers import FAKE_BCRYPT_HASH
    from app.domaine.modeles.auth import Role, User, UserRole

    role_admin = Role(code="admin", libelle="Admin")
    user = User(
        email="admin-test@delicego.local",
        nom_affiche="Admin Test",
        mot_de_passe_hash=FAKE_BCRYPT_HASH,
        actif=True,
    )
    session_test.add_all([role_admin, user])
    await session_test.flush()
    session_test.add(UserRole(user_id=user.id, role_id=role_admin.id))
    await session_test.commit()

    return creer_token_acces(
        secret=parametres_application.jwt_secret,
        sujet=str(user.id),
        duree_minutes=parametres_application.jwt_duree_minutes,
        roles=["admin"],
    )


@pytest.mark.asyncio
async def test_api_planification_cree_un_plan(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jwt = await _creer_user_admin_et_jwt(session_test)
    await _rollback_si_transaction(session_test)
    magasin_id, debut, fin = await _seed_donnees_planification(session_test)

    reponse = await client.post(
        "/api/interne/production/planifier",
        headers=_entetes_internes_admin(jwt),
        json={
            "magasin_id": str(magasin_id),
            "date_plan": "2025-06-03",
            "date_debut_historique": str(debut),
            "date_fin_historique": str(fin),
            "donnees_meteo": {},
            "evenements": [],
        },
    )

    assert reponse.status_code == 201, reponse.text
    plan_id = UUID(reponse.json()["plan_production_id"])

    # Vérifier en base qu’un plan existe
    res = await session_test.execute(select(PlanProduction).where(PlanProduction.id == plan_id))
    plan = res.scalar_one_or_none()
    assert plan is not None

    await client.aclose()


@pytest.mark.asyncio
async def test_api_execution_production_retourne_compteurs(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jwt = await _creer_user_admin_et_jwt(session_test)

    # éviter de réutiliser une transaction ouverte par la fixture/session
    await _rollback_si_transaction(session_test)

    magasin = Magasin(nom="Escat API", type_magasin=TypeMagasin.PRODUCTION, actif=True)
    fournisseur = Fournisseur(nom="Fresh API", actif=True)
    ingredient = Ingredient(nom="Tomate API", unite_stock="kg", unite_consommation="kg", actif=True)

    session_test.add_all([magasin, fournisseur, ingredient])
    await session_test.commit()

    recette = Recette(nom="Recette Salade API")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(nom="Menu Salade API", actif=True, magasin_id=magasin.id, recette_id=recette.id)
    session_test.add(menu)
    await session_test.commit()

    # 0.2 kg de tomate par unité produite
    session_test.add(
        LigneRecette(
            recette_id=recette.id,
            ingredient_id=ingredient.id,
            quantite=0.2,
            unite="kg",
        )
    )
    await session_test.commit()

    aujourd_hui = date.today()

    lot_proche = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="L1",
        date_dlc=aujourd_hui + timedelta(days=1),
        unite="kg",
    )
    lot_lointain = Lot(
        magasin_id=magasin.id,
        ingredient_id=ingredient.id,
        fournisseur_id=fournisseur.id,
        code_lot="L2",
        date_dlc=aujourd_hui + timedelta(days=10),
        unite="kg",
    )
    session_test.add_all([lot_proche, lot_lointain])
    await session_test.commit()

    session_test.add_all(
        [
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient.id,
                lot_id=lot_proche.id,
                quantite=0.3,
                unite="kg",
            ),
            MouvementStock(
                type_mouvement=TypeMouvementStock.RECEPTION,
                magasin_id=magasin.id,
                ingredient_id=ingredient.id,
                lot_id=lot_lointain.id,
                quantite=2.0,
                unite="kg",
            ),
        ]
    )
    await session_test.commit()

    # Production : 5 unités -> besoin 1kg
    lot_production = LotProduction(
        magasin_id=magasin.id,
        plan_production_id=None,
        recette_id=recette.id,
        quantite_produite=5.0,
        unite="unite",
    )
    session_test.add(lot_production)
    await session_test.commit()

    reponse = await client.post(
        f"/api/interne/production/{lot_production.id}/executer",
        headers=_entetes_internes_admin(jwt),
    )

    assert reponse.status_code == 200, reponse.text
    data = reponse.json()
    assert data["nb_mouvements_stock"] == 2
    assert data["nb_lignes_consommation"] == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_api_planification_plan_deja_existant_retourne_409(session_test: AsyncSession) -> None:
    client = await _client_api(session_test)

    jwt = await _creer_user_admin_et_jwt(session_test)
    await _rollback_si_transaction(session_test)

    magasin = Magasin(nom="Magasin Conflit", type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add(magasin)
    await session_test.commit()

    # Plan existant
    plan_existant = PlanProduction(
        magasin_id=magasin.id,
        date_plan=date(2025, 7, 1),
    )
    session_test.add(plan_existant)
    await session_test.commit()

    reponse = await client.post(
        "/api/interne/production/planifier",
        headers=_entetes_internes_admin(jwt),
        json={
            "magasin_id": str(magasin.id),
            "date_plan": "2025-07-01",
            "date_debut_historique": "2025-06-01",
            "date_fin_historique": "2025-06-02",
            "donnees_meteo": {},
            "evenements": [],
        },
    )

    assert reponse.status_code == 409

    await client.aclose()
