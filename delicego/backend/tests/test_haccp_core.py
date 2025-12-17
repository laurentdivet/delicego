from __future__ import annotations

import pytest

from app.domaine.modeles.haccp import (
    Checklist,
    ChecklistAnswer,
    ChecklistItem,
    Equipment,
    ReceptionControl,
    TemperatureLog,
    TraceabilityEvent,
    TraceabilityItem,
    ValidationError,
)


def test_refus_validation_tracabilite_sans_preuve() -> None:
    ev = TraceabilityEvent(items=[TraceabilityItem(dlc_ddm=None, numero_lot=None, photo_path=None)])
    with pytest.raises(ValidationError):
        ev.validate()


@pytest.mark.parametrize(
    "item",
    [
        TraceabilityItem(dlc_ddm=None, numero_lot="LOT-1", photo_path=None),
        TraceabilityItem(dlc_ddm=None, numero_lot=None, photo_path="/tmp/p.jpg"),
    ],
)
def test_acceptation_avec_lot_ou_photo(item: TraceabilityItem) -> None:
    ev = TraceabilityEvent(items=[item])
    ev2 = ev.validate()
    assert ev2.validated is True


def test_acceptation_avec_dlc() -> None:
    from datetime import date

    ev = TraceabilityEvent(items=[TraceabilityItem(dlc_ddm=date(2030, 1, 1), numero_lot=None, photo_path=None)])
    ev2 = ev.validate()
    assert ev2.validated is True


def test_impossibilite_de_modifier_apres_validation() -> None:
    ev = TraceabilityEvent(items=[TraceabilityItem(numero_lot="L1")]).validate()
    with pytest.raises(Exception):
        ev.add_item(TraceabilityItem(numero_lot="L2"))


def test_reception_non_conforme_sans_photo_refusee() -> None:
    rc = ReceptionControl(conforme=False, commentaire="pas ok", photo_path=None)
    with pytest.raises(ValidationError):
        rc.validate()


def test_temperature_conforme_non_conforme() -> None:
    eq = Equipment(nom="Frigo", seuil_min=0.0, seuil_max=4.0)

    t_ok = TemperatureLog(equipment_id=eq.id, valeur=3.0, seuil_min=eq.seuil_min, seuil_max=eq.seuil_max)
    assert t_ok.conforme is True

    t_bad = TemperatureLog(equipment_id=eq.id, valeur=8.0, seuil_min=eq.seuil_min, seuil_max=eq.seuil_max)
    assert t_bad.conforme is False


def test_checklist_non_sans_commentaire_refusee() -> None:
    cl = Checklist(
        titre="Ouverture",
        items=[
            ChecklistItem(
                question="Sol propre?",
                reponse=ChecklistAnswer.NON,
                commentaire=None,
                photo_path="/tmp/p.jpg",
            )
        ],
    )

    with pytest.raises(ValidationError):
        cl.validate()
