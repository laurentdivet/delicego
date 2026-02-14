from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles import Fournisseur, Ingredient
from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
from app.domaine.services.bon_commande_fournisseur import (
    BonCommandeIntrouvable,
    ServiceBonCommandeFournisseur,
)


@pytest.mark.asyncio
async def test_service_genere_un_pdf_en_bytes_sans_ecriture_disque(
    session_test: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Garde-fou : si le service tente d'écrire sur disque via open(), on échoue.
    def _open_interdit(*_args, **_kwargs):
        raise AssertionError("Accès disque interdit (open)")

    monkeypatch.setattr("builtins.open", _open_interdit)

    fournisseur = Fournisseur(nom="Fournisseur PDF", actif=True)
    ingredient = Ingredient(nom="Farine", unite_stock="kg", unite_consommation="kg", cout_unitaire=2.5, actif=True)
    session_test.add_all([fournisseur, ingredient])
    await session_test.commit()

    commande = CommandeFournisseur(
        fournisseur_id=fournisseur.id,
        date_commande=datetime.now(timezone.utc),
        commentaire=None,
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

    service = ServiceBonCommandeFournisseur(session_test)
    pdf = await service.generer_pdf(commande.id)

    assert isinstance(pdf, (bytes, bytearray))
    assert bytes(pdf).startswith(b"%PDF")
    assert len(pdf) > 0


@pytest.mark.asyncio
async def test_service_pdf_commande_introuvable(session_test: AsyncSession) -> None:
    service = ServiceBonCommandeFournisseur(session_test)
    with pytest.raises(BonCommandeIntrouvable):
        await service.generer_pdf(uuid4())
