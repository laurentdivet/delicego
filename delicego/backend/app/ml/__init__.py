"""ML package (prévision ventes).

Ce package contient un pipeline minimal mais robuste:
- extraction dataset depuis la DB (async SQLAlchemy)
- entraînement (XGBoost si dispo, sinon baseline)
- prédiction J+1..J+N et écriture en DB (prediction_vente)

Objectif: être appelable depuis un service (cron / endpoint) sans dépendre du front.
"""
