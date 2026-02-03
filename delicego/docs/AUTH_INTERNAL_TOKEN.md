# Auth interne minimale (Bearer token)

Objectif: protéger toutes les routes **/api/interne/** via un token statique transmis dans:

```http
Authorization: Bearer <token>
```

## Backend (FastAPI)

### Variable d’environnement

- `INTERNAL_API_TOKEN`
  - **obligatoire en prod**
  - en dev: si absent, fallback sur `dev-token` avec un warning.

Exemple:

```bash
export INTERNAL_API_TOKEN='change-me-super-long-random'
uvicorn app.main:app --reload
```

### Curl (smoke)

Sans token:

```bash
curl -i http://localhost:8000/api/interne/impact/dashboard
```

Avec token:

```bash
curl -i \
  -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
  "http://localhost:8000/api/interne/impact/dashboard?days=30&limit=200"

```

## API Impact interne (read + write)

### Lire le dashboard

```bash
curl -s \
  -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
  "http://localhost:8000/api/interne/impact/dashboard?days=30&limit=200" | jq
```

### Créer une action sur une recommandation

```bash
RECO_ID='<uuid-recommendation-event>'

curl -s -X POST \
  -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  "http://localhost:8000/api/interne/impact/recommendations/${RECO_ID}/actions" \
  -d '{"action_type":"MANUAL","description":"Appeler le fournisseur"}' | jq
```

### Mettre à jour une action

```bash
ACTION_ID='<uuid-action>'

curl -s -X PATCH \
  -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  "http://localhost:8000/api/interne/impact/actions/${ACTION_ID}" \
  -d '{"status":"DONE"}' | jq
```

### Mettre à jour une recommandation

```bash
RECO_ID='<uuid-recommendation-event>'

curl -s -X PATCH \
  -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  "http://localhost:8000/api/interne/impact/recommendations/${RECO_ID}" \
  -d '{"status":"ACKNOWLEDGED","comment":"Pris en compte"}' | jq
```

## Frontend (Vite)

### Activer l’utilisation de l’API interne

Définir:

```bash
VITE_USE_INTERNAL_API=1
```

En dev (exemple):

```bash
cd frontend
VITE_USE_INTERNAL_API=1 npm run dev
```

### Saisir le token

Sur la page **/impact**, un bloc "Accès interne" permet de saisir le token.

- il est sauvegardé dans `localStorage` sous la clé: `INTERNAL_TOKEN`
- le client `frontend/src/api/interne.ts` l’envoie automatiquement dans `Authorization: Bearer ...`

## Tests

```bash
cd backend
pytest -q tests/test_internal_auth_smoke.py
```
