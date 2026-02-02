# Auth minimale (JWT) – delicego

## Vue d'ensemble

- Backend : **FastAPI + SQLAlchemy async**.
- Auth : **JWT Bearer** (endpoint `/auth/login`) avec mot de passe **bcrypt**.
- Rôles : `admin`, `operateur`.
- API interne : on conserve le header technique `X-CLE-INTERNE`.
- Endpoints sensibles (production) : **X-CLE-INTERNE + JWT requis**.

## Backend

### Endpoints

- `POST /auth/login` : renvoie `{ token_acces, type_token }`
- `GET /auth/me` : renvoie l'utilisateur courant (id/email/nom_affiche/roles)

### Dépendances

- `app.api.dependances_auth.fournir_utilisateur_courant` : lit `Authorization: Bearer <token>`.
- `app.api.dependances_auth.verifier_authentifie` : exige un utilisateur authentifié.
- `app.api.dependances_auth.verifier_roles_requis("admin", ...)` : garde par rôles.

### Rôles / seed

Le script `backend/scripts/seed_socle.py` crée :

- rôles : `admin`, `operateur`
- utilisateur : `admin@delicego.local` / `ChangeMe123!` avec rôle `admin`

Lancer :

```bash
cd backend
python -m app.scripts.seed_socle
```

## Frontend

### Login

Page : `/login`.

Après login :
- le token JWT est stocké en `localStorage` sous la clé `delicego_token`.

### Appels API interne

Le client `frontend/src/api/interne.ts` ajoute automatiquement :

- `X-CLE-INTERNE: <VITE_CLE_INTERNE>`
- `Authorization: Bearer <delicego_token>` (si présent)

### Protection des routes

Les routes de l'app sont encapsulées dans `ProtectedRoute`.
Si l'utilisateur n'est pas loggé : redirection vers `/login`.
