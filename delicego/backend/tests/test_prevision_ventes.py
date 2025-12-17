from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import CanalVente, TypeMagasin
from app.domaine.modeles import Magasin, Menu, Recette
from app.domaine.modeles.ventes_prevision import ExecutionPrevision, LignePrevision, Vente
from app.main import creer_application


def _client_interne() -> TestClient:
    return TestClient(creer_application())


def _entetes_internes() -> dict[str, str]:
    return {"X-CLE-INTERNE": "cle-technique"}


@pytest.mark.asyncio
async def test_prevision_ventes_par_produit_et_fiabilite(session_test: AsyncSession) -> None:
    client = _client_interne()

    magasin = Magasin(nom="PV", type_magasin=TypeMagasin.VENTE, actif=True)
    session_test.add(magasin)
    await session_test.commit()

    recette = Recette(nom="Recette PV")
    session_test.add(recette)
    await session_test.flush()

    menu = Menu(
        nom="Menu PV",
        actif=True,
        magasin_id=magasin.id,
        recette_id=recette.id,
        prix=10.0,
        commandable=True,
    )
    session_test.add(menu)
    await session_test.commit()

    # Ventes réelles le 2025-01-01 : 5 unités
    session_test.add(
        Vente(
            magasin_id=magasin.id,
            date_vente=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            canal=CanalVente.COMPTOIR,
            menu_id=menu.id,
            quantite=5.0,
        )
    )

    # Ventes + prévision sur historique (pour fiabilité): 2024-12-31
    session_test.add(
        Vente(
            magasin_id=magasin.id,
            date_vente=datetime(2024, 12, 31, 12, 0, 0, tzinfo=timezone.utc),
            canal=CanalVente.COMPTOIR,
            menu_id=menu.id,
            quantite=10.0,
        )
    )
    await session_test.commit()

    exec_prev = ExecutionPrevision(magasin_id=magasin.id)
    session_test.add(exec_prev)
    await session_test.commit()

    # Prévision 2025-01-01 : 6 unités
    session_test.add(
        LignePrevision(
            execution_prevision_id=exec_prev.id,
            date_prevue=date(2025, 1, 1),
            menu_id=menu.id,
            quantite_prevue=6.0,
        )
    )

    # Prévision historique 2024-12-31 : 8 unités
    session_test.add(
        LignePrevision(
            execution_prevision_id=exec_prev.id,
            date_prevue=date(2024, 12, 31),
            menu_id=menu.id,
            quantite_prevue=8.0,
        )
    )
    await session_test.commit()

    r = client.get(
        "/api/interne/previsions/ventes",
        headers=_entetes_internes(),
        params={"date_cible": "2025-01-01", "magasin_id": str(magasin.id), "fenetre_fiabilite_jours": 2},
    )
    assert r.status_code == 200
    data = r.json()

    assert data["date_cible"] == "2025-01-01"
    assert data["magasin_id"] == str(magasin.id)

    # Totaux
    assert data["ca_reel"] == 50.0
    assert data["ca_prevu"] == 60.0

    # Table produit
    assert len(data["table_produits"]) == 1
    lp = data["table_produits"][0]
    assert lp["menu_id"] == str(menu.id)
    assert lp["quantite_vendue"] == 5.0
    assert lp["quantite_prevue"] == 6.0

    # Fiabilité (doit être calculée, pas forcément valeur exacte ici)
    assert data["fiabilite"]["wape_ca_pct"] is not None
