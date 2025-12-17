# DéliceGo — Backend

Backend unique (structure) fusionnant :
- **Prévision + plan de production** (inspiration Inpulse)
- **Traçabilité + hygiène** (inspiration Trackfood)

## Démarrage rapide

### Prérequis
- Python **3.12+**
- Docker (pour PostgreSQL)

### Base de données
À la racine du dépôt :

```bash
docker compose up -d
```

### Installation

```bash
cd delicego/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Migrations

```bash
cd delicego/backend
alembic upgrade head
```

### Lancer l’application

```bash
cd delicego/backend
uvicorn app.main:app --reload
```

Endpoint disponible :
- `GET /health`

### Tests

```bash
cd delicego/backend
pytest
```

> Note : ce projet n’expose **aucune API métier** pour l’instant (uniquement `/health`).
