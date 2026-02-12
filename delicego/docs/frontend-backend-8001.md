# Frontend ↔ Backend : dev sur le port 8001 (Impact / API interne)

Objectif : en dev, éviter les 404 (ex: appels résiduels à `/auth/login`) et s’aligner sur le backend FastAPI lancé sur **8001**.

## Pré-requis

- Node/NPM installés
- Backend FastAPI `backend/` fonctionnel

## Démarrage backend (8001)

```bash
cd backend
export INTERNAL_API_TOKEN=ton-token
uvicorn app.main:app --reload --port 8001
```

Vérification :

- ouvrir `http://127.0.0.1:8001/docs`

## Démarrage frontend (Vite)

```bash
cd frontend
VITE_USE_INTERNAL_API=1 npm run dev
```

### Ce que fait le frontend

- Toutes les routes API sont appelées en relatif (`/api/...`).
- En dev, Vite proxifie `/api` vers `VITE_API_BASE_URL`.
- Par défaut, on utilise `VITE_API_BASE_URL=http://127.0.0.1:8001`.

Fichiers env (dev) :

- `frontend/.env.development` : `VITE_API_BASE_URL=http://127.0.0.1:8001`
- `frontend/.env.local` (optionnel, override local) : `VITE_API_BASE_URL=http://127.0.0.1:8001`

## Test manuel guidé

1) Aller sur `http://localhost:5173/login`
2) En mode interne (`VITE_USE_INTERNAL_API=1`), saisir le token et valider
3) Aller sur `/impact`

Dans l’onglet **Network** (DevTools) :

- Vérifier que les appels partent vers `http://127.0.0.1:8001/api/...` (ou apparaissent en `/api/...` côté browser mais sont proxifiés vers 8001).
- Endpoint attendu en lecture dashboard :
  - `GET /api/interne/impact/dashboard`

## Anti-régression

- Le frontend ne doit plus appeler `/auth/login` (connexion JWT non supportée en interne).
