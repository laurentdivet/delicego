# Gel du backend — état de référence

Objectif : **geler le backend** pour passer en mode produit/vente.

## Ce qui est gelé
- Aucune modification de logique métier / modèles / endpoints.
- L’API opérationnelle cuisine est considérée **source de vérité**.

## Endpoints cuisine (référence)
Préfixe : `/api/interne/production-preparation`
- `GET /api/interne/production-preparation` (magasin_id, date)
- `POST /api/interne/production-preparation/produit`
- `POST /api/interne/production-preparation/ajuste`
- `POST /api/interne/production-preparation/non-produit`
- `GET /api/interne/production-preparation/traceabilite` (magasin_id, date, recette_id)

## Tests de non-régression backend (doivent rester verts)
- `cd backend && pytest -q`

## Consigne produit
- Toute évolution doit passer par :
  1) ticket
  2) justification métier
  3) tests
  4) validation
