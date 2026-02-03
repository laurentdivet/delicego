from __future__ import annotations

from fastapi import APIRouter

# ===== Endpoints internes =====
from app.api.endpoints.production import routeur_production_interne
from app.api.endpoints.production_preparation import routeur_production_preparation_interne
from app.api.endpoints.production_reelle import routeur_production_reelle_interne
from app.api.endpoints.dashboard import routeur_dashboard
from app.api.endpoints.comptabilite import routeur_comptabilite
from app.api.endpoints.couts import routeur_couts_interne
from app.api.endpoints.haccp import routeur_haccp_interne
from app.api.endpoints.haccp_documents import routeur_haccp_documents
from app.api.endpoints.achats import routeur_achats_interne
from app.api.endpoints.dashboard_fournisseurs import routeur_dashboard_fournisseurs_interne
from app.api.endpoints.dashboard_production_stock import routeur_dashboard_production_stock_interne
from app.api.endpoints.kpis import routeur_kpis_interne
from app.api.endpoints.prevision_ventes import routeur_prevision_ventes_interne
from app.api.endpoints.previsions_besoins import routeur_previsions_besoins_interne
from app.api.endpoints.previsions_alertes import routeur_previsions_alertes_interne
from app.api.endpoints.analytics import routeur_analytics
from app.api.endpoints.production_jour import routeur_production_jour_interne
from app.api.endpoints.impact import routeur_impact_interne

# ===== Endpoints client =====
from app.api.endpoints.commande_client import routeur_commande_client
from app.api.endpoints.auth import routeur_auth
from app.api.endpoints.utilisateurs import routeur_utilisateurs


# ==============================
# ROUTEUR PRINCIPAL
# ==============================
router = APIRouter()

# Auth
router.include_router(routeur_auth)

# Socle utilisateurs (API interne)
router.include_router(routeur_utilisateurs)


# ==============================
# API INTERNE
# ==============================
routeur_interne = APIRouter(prefix="/api/interne")

routeur_interne.include_router(routeur_production_interne)
routeur_interne.include_router(routeur_production_preparation_interne)
routeur_interne.include_router(routeur_production_reelle_interne)
routeur_interne.include_router(routeur_dashboard)
routeur_interne.include_router(routeur_comptabilite)
routeur_interne.include_router(routeur_couts_interne)
routeur_interne.include_router(routeur_haccp_interne)
routeur_interne.include_router(routeur_achats_interne)
routeur_interne.include_router(routeur_dashboard_fournisseurs_interne)
routeur_interne.include_router(routeur_dashboard_production_stock_interne)
routeur_interne.include_router(routeur_kpis_interne)
routeur_interne.include_router(routeur_prevision_ventes_interne)
routeur_interne.include_router(routeur_previsions_besoins_interne)
routeur_interne.include_router(routeur_previsions_alertes_interne)
routeur_interne.include_router(routeur_production_jour_interne)
routeur_interne.include_router(routeur_impact_interne)

router.include_router(routeur_interne)

# HACCP documents (racine, hors /api/interne) pour correspondre aux routes strictes /documents/*
router.include_router(routeur_haccp_documents)

# Analytics (read-only) à la racine
router.include_router(routeur_analytics)


# ==============================
# API CLIENT PUBLIQUE
# ==============================
router.include_router(routeur_commande_client)
