from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class PointHoraireVentes(BaseModel):
    heure: int  # 0-23

    quantite_prevue: float
    quantite_reelle: float
    ecart_quantite: float

    ca_prevu: float
    ca_reel: float
    ecart_ca: float


class LignePrevisionProduit(BaseModel):
    menu_id: str
    menu_nom: str

    quantite_prevue: float
    quantite_vendue: float
    ecart_quantite: float

    ca_prevu: float
    ca_reel: float
    ecart_ca: float

    # optionnel (si le modèle prend en compte des facteurs)
    impact_meteo_pct: float | None = None
    impact_jour_ferie_pct: float | None = None


class FiabiliteModele(BaseModel):
    """Qualité de la prévision sur une fenêtre d'historique (MVP).

    - WAPE = sum(|erreur|) / sum(reel)
    - MAPE = moyenne(|erreur| / reel) (en ignorant les jours reel=0)
    - fiabilite_pct = 100 - WAPE% (simple et lisible)
    """

    wape_ca_pct: float | None = None
    mape_ca_pct: float | None = None
    fiabilite_ca_pct: float | None = None


class ReponsePrevisionVentes(BaseModel):
    magasin_id: str | None = None
    date_cible: date

    # Synthèse
    ca_prevu: float
    ca_reel: float
    ecart_ca: float

    quantite_prevue: float
    quantite_reelle: float
    ecart_quantite: float

    fiabilite: FiabiliteModele

    # Détails clés
    courbe_horaire: list[PointHoraireVentes]
    table_produits: list[LignePrevisionProduit]

    facteurs: dict[str, bool] = {
        "meteo_active": False,
        "jour_ferie_active": False,
    }
