from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.domaine.modeles.operations import (
    InMemoryOperationsStore,
    Inventory,
    InventoryLine,
    Loss,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    StockMovement,
    StockMovementType,
    Transfer,
    TransferLine,
    ValidationError,
    compute_stock,
)


def test_calcul_stock_via_mouvements_uniquement() -> None:
    p = uuid4()
    e = uuid4()
    u = uuid4()

    moves = [
        StockMovement(produit_id=p, etablissement_id=e, type=StockMovementType.ENTREE, quantite=10, valeur_unitaire=2, utilisateur_id=u),
        StockMovement(produit_id=p, etablissement_id=e, type=StockMovementType.SORTIE, quantite=3, valeur_unitaire=2, utilisateur_id=u),
    ]

    stock = compute_stock(moves, produit_id=p, etablissement_id=e)
    assert stock.quantite == 7


def test_inventaire_genere_mouvements_correctifs() -> None:
    p = uuid4()
    e = uuid4()
    u = uuid4()

    moves = [
        StockMovement(produit_id=p, etablissement_id=e, type=StockMovementType.ENTREE, quantite=10, valeur_unitaire=1, utilisateur_id=u)
    ]

    inv = Inventory(date=date.today(), etablissement_id=e, utilisateur_id=u, lines=[InventoryLine(produit_id=p, quantite_comptee=8)])
    inv2, created = inv.validate(existing_movements=moves)

    assert inv2.validated is True
    assert len(created) == 1
    assert created[0].type == StockMovementType.INVENTAIRE
    assert created[0].quantite == -2


def test_transfert_sortant_entrant_coherent() -> None:
    p = uuid4()
    src = uuid4()
    dst = uuid4()
    u = uuid4()

    moves = [
        StockMovement(produit_id=p, etablissement_id=src, type=StockMovementType.ENTREE, quantite=5, valeur_unitaire=3, utilisateur_id=u)
    ]

    tr = Transfer(source_etablissement_id=src, cible_etablissement_id=dst, date=date.today(), lines=[TransferLine(produit_id=p, quantite=2)])
    tr2, out_moves = tr.envoyer(existing_movements=moves, utilisateur_id=u)
    assert tr2.statut.value == "ENVOYE"
    assert out_moves[0].type == StockMovementType.TRANSFERT_SORTANT

    moves2 = moves + out_moves
    tr3, in_moves = tr2.recevoir(existing_movements=moves2, utilisateur_id=u)
    assert tr3.statut.value == "RECU"
    assert in_moves[0].type == StockMovementType.TRANSFERT_ENTRANT
    assert in_moves[0].valeur_unitaire == 3


def test_perte_genere_sortie_stock() -> None:
    p = uuid4()
    e = uuid4()
    u = uuid4()

    moves = [
        StockMovement(produit_id=p, etablissement_id=e, type=StockMovementType.ENTREE, quantite=5, valeur_unitaire=4, utilisateur_id=u)
    ]

    loss = Loss(produit_id=p, etablissement_id=e, quantite=1, motif="casse", date=date.today(), utilisateur_id=u)
    loss2, move = loss.validate(existing_movements=moves)
    assert loss2.validated is True
    assert move.type == StockMovementType.PERTE
    assert move.quantite == 1


def test_reception_commande_genere_entree_stock() -> None:
    p = uuid4()
    e = uuid4()
    u = uuid4()

    po = PurchaseOrder(
        fournisseur_id=uuid4(),
        etablissement_id=e,
        date=date.today(),
        statut=PurchaseOrderStatus.BROUILLON,
        lines=[PurchaseOrderLine(produit_id=p, quantite=10, prix_unitaire=2.5)],
    )

    po2 = po.envoyer()
    assert po2.statut == PurchaseOrderStatus.ENVOYEE

    po3, moves = po2.recevoir(utilisateur_id=u)
    assert po3.statut == PurchaseOrderStatus.RECUE
    assert len(moves) == 1
    assert moves[0].type == StockMovementType.ENTREE
    assert moves[0].quantite == 10
    assert moves[0].valeur_unitaire == 2.5


def test_impossibilite_modifier_apres_validation() -> None:
    # inventory validé ne peut pas être re-validé
    p = uuid4()
    e = uuid4()
    u = uuid4()

    inv = Inventory(date=date.today(), etablissement_id=e, utilisateur_id=u, lines=[InventoryLine(produit_id=p, quantite_comptee=0)])
    inv2, _ = inv.validate(existing_movements=[])

    with pytest.raises(Exception):
        inv2.validate(existing_movements=[])

    # perte: motif obligatoire
    with pytest.raises(ValidationError):
        Loss(produit_id=p, etablissement_id=e, quantite=1, motif="", date=date.today(), utilisateur_id=u).validate(existing_movements=[])

    # store movements append-only
    store = InMemoryOperationsStore()
    store.append_movement(StockMovement(produit_id=p, etablissement_id=e, type=StockMovementType.ENTREE, quantite=1, valeur_unitaire=1, utilisateur_id=u))
    assert len(store.movements) == 1
