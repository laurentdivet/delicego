"""Modèles SQLAlchemy.

On ne met aucune logique métier ici : uniquement la structure des tables.
"""

from app.domaine.modeles.base import BaseModele, ModeleHorodate
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, LigneRecette, Magasin, Menu, Recette, Utilisateur
from app.domaine.modeles.auth import Role, User, UserRole
from app.domaine.modeles.audit import AuditLog
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock
from app.domaine.modeles.achats import (
    CommandeAchat,
    LigneCommandeAchat,
    ReceptionMarchandise,
    LigneReceptionMarchandise,
    CommandeFournisseur,
    LigneCommandeFournisseur,
)
from app.domaine.modeles.ventes_prevision import ExecutionPrevision, LignePrevision, Vente
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.comptabilite import EcritureComptable, JournalComptable
from app.domaine.modeles.production import (
    LigneConsommation,
    LignePlanProduction,
    LotProduction,
    PlanProduction,
)
from app.domaine.modeles.hygiene import (
    ActionCorrective,
    ControleHACCP,
    EquipementThermique,
    JournalNettoyage,
    NonConformiteHACCP,
    ReleveTemperature,
)

__all__ = [
    "BaseModele",
    "ModeleHorodate",
    # Référentiel
    "Magasin",
    "Utilisateur",
    # Auth
    "User",
    "Role",
    "UserRole",
    "AuditLog",
    "Fournisseur",
    "Ingredient",
    "Menu",
    "Recette",
    "LigneRecette",
    # Stock & traçabilité
    "Lot",
    "MouvementStock",
    # Achats
    "CommandeAchat",
    "LigneCommandeAchat",
    "ReceptionMarchandise",
    "LigneReceptionMarchandise",
    "CommandeFournisseur",
    "LigneCommandeFournisseur",
    # Ventes & prévision
    "Vente",
    "ExecutionPrevision",
    "LignePrevision",
    # Commande client
    "CommandeClient",
    "LigneCommandeClient",
    # Comptabilité
    "EcritureComptable",
    "JournalComptable",
    # Production
    "PlanProduction",
    "LignePlanProduction",
    "LotProduction",
    "LigneConsommation",
    # Hygiène
    "EquipementThermique",
    "ReleveTemperature",
    "ControleHACCP",
    "JournalNettoyage",
    "NonConformiteHACCP",
    "ActionCorrective",
]
