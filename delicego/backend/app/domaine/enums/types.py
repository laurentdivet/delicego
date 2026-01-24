from __future__ import annotations

import enum


class TypeMouvementStock(str, enum.Enum):
    RECEPTION = "RECEPTION"
    CONSOMMATION = "CONSOMMATION"
    AJUSTEMENT = "AJUSTEMENT"
    PERTE = "PERTE"
    TRANSFERT = "TRANSFERT"


class CanalVente(str, enum.Enum):
    """Canal par lequel une vente est réalisée.

    NOTE : la base de données utilise l'enum PostgreSQL `canalvente`.
    Dans l'environnement actuel, les valeurs présentes en DB sont :
    - INTERNE
    - EXTERNE
    - AUTRE

    On aligne donc l'Enum Python sur ces valeurs.
    """

    INTERNE = "INTERNE"
    EXTERNE = "EXTERNE"
    AUTRE = "AUTRE"


class StatutPlanProduction(str, enum.Enum):
    BROUILLON = "BROUILLON"
    VERROUILLE = "VERROUILLE"
    TERMINE = "TERMINE"


class StatutCommandeClient(str, enum.Enum):
    """Statut d’une commande client (canal en ligne)."""

    EN_ATTENTE = "EN_ATTENTE"
    CONFIRMEE = "CONFIRMEE"
    ANNULEE = "ANNULEE"


class StatutCommandeFournisseur(str, enum.Enum):
    """Statut d’une commande fournisseur (achats).

    Règle : le stock n’est impacté que lors des réceptions (totales ou partielles).
    """

    BROUILLON = "BROUILLON"
    ENVOYEE = "ENVOYEE"
    PARTIELLE = "PARTIELLE"
    RECEPTIONNEE = "RECEPTIONNEE"


class TypeEcritureComptable(str, enum.Enum):
    """Type d’écriture comptable.

    IMPORTANT :
    Pennylane est une projection comptable : aucune logique métier ici.
    """

    VENTE = "VENTE"
    ACHAT = "ACHAT"


class TypeMagasin(str, enum.Enum):
    """
    Type de site.
    - PRODUCTION : site central (ex : Escat)
    - VENTE : point de vente
    """
    PRODUCTION = "PRODUCTION"
    VENTE = "VENTE"


class TypeEquipementThermique(str, enum.Enum):
    VITRINE = "VITRINE"
    FRIGO = "FRIGO"
    CHAMBRE_FROIDE = "CHAMBRE_FROIDE"


class ZoneEquipementThermique(str, enum.Enum):
    VENTE = "VENTE"
    CUISINE = "CUISINE"
    PRODUCTION = "PRODUCTION"
