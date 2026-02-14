from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_email_client, fournir_session
from app.domaine.enums.types import StatutCommandeFournisseur
from app.domaine.modeles import Fournisseur, Ingredient
from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
from app.domaine.services.email_client import FakeEmailClient
from app.domaine.services.envoyer_commande_fournisseur import (
    EchecEnvoiEmailCommandeFournisseur,
    ServiceEnvoiCommandeFournisseur,
    TransitionStatutInterditeEnvoiCommandeFournisseur,
)
from app.main import creer_application
from tests._http_helpers import entetes_internes


def _app_avec_dependances_test(session_test: AsyncSession, *, email_client: FakeEmailClient):
    app = creer_application()

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

    async def _fournir_session_override():
        assert session_test.bind is not None
        async with _AsyncSession(bind=session_test.bind, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[fournir_session] = _fournir_session_override
    app.dependency_overrides[fournir_email_client] = lambda: email_client
    return app


async def _client_api(session_test: AsyncSession, *, email_client: FakeEmailClient) -> httpx.AsyncClient:
    app = _app_avec_dependances_test(session_test, email_client=email_client)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _entetes_internes() -> dict[str, str]:
    return entetes_internes()


@pytest.mark.asyncio
async def test_service_envoie_email_avec_pdf_et_passe_a_envoyee(
    session_test: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # garde-fou anti-écriture disque
    def _open_interdit(*_args, **_kwargs):
        raise AssertionError("Accès disque interdit (open)")

    monkeypatch.setattr("builtins.open", _open_interdit)

    fournisseur = Fournisseur(nom="Fournisseur Email", actif=True)
    ingredient = Ingredient(nom="Farine", unite_stock="kg", unite_consommation="kg", cout_unitaire=2.5, actif=True)
    session_test.add_all([fournisseur, ingredient])
    await session_test.commit()

    commande = CommandeFournisseur(
        fournisseur_id=fournisseur.id,
        date_commande=datetime.now(timezone.utc),
        statut=StatutCommandeFournisseur.BROUILLON,
    )
    session_test.add(commande)
    await session_test.flush()

    session_test.add(
        LigneCommandeFournisseur(
            commande_fournisseur_id=commande.id,
            ingredient_id=ingredient.id,
            quantite=3.0,
            quantite_recue=0.0,
            unite="kg",
        )
    )
    await session_test.commit()

    fake = FakeEmailClient()
    service = ServiceEnvoiCommandeFournisseur(session_test, email_client=fake)

    await service.envoyer(
        commande_fournisseur_id=commande.id,
        destinataire="test@example.com",
        sujet="Commande",
        corps="Bonjour",
    )

    assert len(fake.emails) == 1
    assert fake.emails[0].destinataire == "test@example.com"
    assert fake.emails[0].pieces_jointes

    nom, data = fake.emails[0].pieces_jointes[0]
    assert nom.endswith(".pdf")
    assert isinstance(data, (bytes, bytearray))
    assert bytes(data).startswith(b"%PDF")
    assert len(data) > 0

    res = await session_test.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == commande.id))
    commande_db = res.scalar_one()
    assert commande_db.statut == StatutCommandeFournisseur.ENVOYEE


@pytest.mark.asyncio
async def test_service_double_envoi_interdit(session_test: AsyncSession) -> None:
    fournisseur = Fournisseur(nom="Fournisseur Email2", actif=True)
    ingredient = Ingredient(nom="Sucre", unite_stock="kg", unite_consommation="kg", cout_unitaire=1.0, actif=True)
    session_test.add_all([fournisseur, ingredient])
    await session_test.commit()

    commande = CommandeFournisseur(
        fournisseur_id=fournisseur.id,
        date_commande=datetime.now(timezone.utc),
        statut=StatutCommandeFournisseur.BROUILLON,
    )
    session_test.add(commande)
    await session_test.flush()

    session_test.add(
        LigneCommandeFournisseur(
            commande_fournisseur_id=commande.id,
            ingredient_id=ingredient.id,
            quantite=1.0,
            quantite_recue=0.0,
            unite="kg",
        )
    )
    await session_test.commit()

    fake = FakeEmailClient()
    service = ServiceEnvoiCommandeFournisseur(session_test, email_client=fake)

    await service.envoyer(
        commande_fournisseur_id=commande.id,
        destinataire="test@example.com",
        sujet="Commande",
        corps="Bonjour",
    )

    with pytest.raises(TransitionStatutInterditeEnvoiCommandeFournisseur):
        await service.envoyer(
            commande_fournisseur_id=commande.id,
            destinataire="test@example.com",
            sujet="Commande",
            corps="Bonjour",
        )

    assert len(fake.emails) == 1


@pytest.mark.asyncio
async def test_service_rollback_si_email_echoue(session_test: AsyncSession) -> None:
    class EmailClientQuiEchoue:
        async def envoyer(
            self,
            *,
            destinataire: str,
            sujet: str,
            corps: str,
            pieces_jointes: list[tuple[str, bytes]],
        ) -> None:
            raise RuntimeError("boom")

    fournisseur = Fournisseur(nom="Fournisseur Email3", actif=True)
    ingredient = Ingredient(nom="Sel", unite_stock="kg", unite_consommation="kg", cout_unitaire=1.0, actif=True)
    session_test.add_all([fournisseur, ingredient])
    await session_test.commit()

    commande = CommandeFournisseur(
        fournisseur_id=fournisseur.id,
        date_commande=datetime.now(timezone.utc),
        statut=StatutCommandeFournisseur.BROUILLON,
    )
    session_test.add(commande)
    await session_test.flush()

    session_test.add(
        LigneCommandeFournisseur(
            commande_fournisseur_id=commande.id,
            ingredient_id=ingredient.id,
            quantite=1.0,
            quantite_recue=0.0,
            unite="kg",
        )
    )
    await session_test.commit()

    service = ServiceEnvoiCommandeFournisseur(session_test, email_client=EmailClientQuiEchoue())

    commande_id = commande.id
    with pytest.raises(EchecEnvoiEmailCommandeFournisseur):
        await service.envoyer(
            commande_fournisseur_id=commande_id,
            destinataire="test@example.com",
            sujet="Commande",
            corps="Bonjour",
        )

    res = await session_test.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == commande_id))
    commande_db = res.scalar_one()
    assert commande_db.statut == StatutCommandeFournisseur.BROUILLON


@pytest.mark.asyncio
async def test_api_envoyer_commande_fournisseur_email(session_test: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    # garde-fou anti-écriture disque
    def _open_interdit(*_args, **_kwargs):
        raise AssertionError("Accès disque interdit (open)")

    monkeypatch.setattr("builtins.open", _open_interdit)

    fournisseur = Fournisseur(nom="Fournisseur API Email", actif=True)
    ingredient = Ingredient(nom="Beurre", unite_stock="kg", unite_consommation="kg", cout_unitaire=5.0, actif=True)
    session_test.add_all([fournisseur, ingredient])
    await session_test.commit()

    commande = CommandeFournisseur(
        fournisseur_id=fournisseur.id,
        date_commande=datetime.now(timezone.utc),
        statut=StatutCommandeFournisseur.BROUILLON,
    )
    session_test.add(commande)
    await session_test.flush()

    session_test.add(
        LigneCommandeFournisseur(
            commande_fournisseur_id=commande.id,
            ingredient_id=ingredient.id,
            quantite=1.0,
            quantite_recue=0.0,
            unite="kg",
        )
    )
    await session_test.commit()

    fake = FakeEmailClient()
    client = await _client_api(session_test, email_client=fake)

    r = await client.post(
        f"/api/interne/achats/{commande.id}/envoyer",
        headers=_entetes_internes(),
        json={"destinataire": "test@example.com", "sujet": "Cmd", "corps": "Bonjour"},
    )
    assert r.status_code == 200

    assert len(fake.emails) == 1
    assert fake.emails[0].pieces_jointes
    assert len(fake.emails[0].pieces_jointes[0][1]) > 0

    # second envoi => 409
    r2 = await client.post(
        f"/api/interne/achats/{commande.id}/envoyer",
        headers=_entetes_internes(),
        json={"destinataire": "test@example.com", "sujet": "Cmd", "corps": "Bonjour"},
    )
    assert r2.status_code == 409

    await client.aclose()
