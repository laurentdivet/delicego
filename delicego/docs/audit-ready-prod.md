# Audit final — prêt pour usage réel (cuisine)

## Portée
- Couche opérationnelle cuisine (lecture + actions opérateur + traçabilité) via API interne.
- UI minimal React branchée (page `/cuisine`).

## ✅ Prêt (MVP utilisable)
### Backend
- Endpoints cuisine disponibles sous `/api/interne/production-preparation`.
- Tests backend : `cd backend && pytest -q` ✅ (59 passed).
- OpenAPI/Swagger : endpoints présents (vérifié via `creer_application().openapi()`).

### Frontend
- Page **Cuisine** disponible : `/cuisine`.
- Boutons opérateur : Produit / Ajusté / Non produit.
- Traçabilité lisible (panneau latéral).
- Build OK : `cd frontend && npm run build` ✅.

## ⚠️ Points à cadrer avant conditions réelles
1) **Saisie magasin_id**
- Actuel : saisie UUID manuelle.
- Risque : erreurs opérateur.
- Mitigation (sans toucher au backend) : fournir l’UUID magasin dans un paramétrage UI (ex: `.env` frontend) ou doc d’exploitation.

2) **Sécurité accès interne**
- Actuel : header `X-CLE-INTERNE` (clé technique).
- Risque : exposition si fuite.
- Mitigation : gestion de secret en prod + reverse proxy / réseau interne.

3) **Données prérequis pour “Produit/Ajusté”**
- Une recette doit avoir une BOM (lignes recette) + stock suffisant sinon l’API retournera une erreur.
- Mitigation : procédure d’onboarding données (recettes + stocks) + message d’erreur UI (déjà affiché).

4) **Observabilité**
- Logs : dépend du runtime uvicorn.
- Mitigation : centraliser logs en prod.

## Commandes de démarrage (dev)
Backend :
- `cd backend && uvicorn app.main:app --reload --port 8000`

Frontend :
- `cd frontend && npm run dev`

URL :
- `http://localhost:5174/cuisine` (selon port Vite affiché)
