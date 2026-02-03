# DéliceGo — Backend

## CI / Reproductibilité (migrations + seed)

La CI GitHub Actions vise à garantir qu'une DB vide est reproductible via:

1) `alembic upgrade head` (pas de downgrade en CI)
2) Checks Postgres:
   - `information_schema.columns` : 0 colonnes `USER-DEFINED`
   - `pg_type` (schema public) : 0 enums natifs
3) `python -m scripts.seed_all --apply` (doit fonctionner **sans XLSX**)

### Commandes locales équivalentes

Pré-requis: Postgres local, une DB vide nommée `delicego`.

```bash
export DATABASE_URL='postgresql+asyncpg://delicego:delicego@localhost:5432/delicego'

# (optionnel) créer la DB si besoin
createdb -h localhost -p 5432 -U delicego delicego

cd backend
pip install -r requirements.txt

# Validations CI (migrations + checks + seed)
python -m scripts.ci_validate
```

Notes:
- La CI est en "Solution 2": aucun ENUM PostgreSQL natif attendu.
- La migration `zzzz` n'est pas downgradable => aucun downgrade n'est exécuté en CI.

## Prévisions (pipeline ML ventes → besoins ingrédients)

Le backend inclut un pipeline ML simple (XGBoost) qui :

1. extrait les ventes journalières par (magasin, menu)
2. entraîne un modèle (features calendaires + lags)
3. génère des prédictions futures dans la table `prediction_vente`
4. expose une API interne pour calculer :
   - les **besoins ingrédients futurs** (BOM)
   - les **alertes rupture/surstock** (MVP)

⚠️ Granularité: la prévision est **au niveau MENU** (`menu_id`) (quantité vendue d'un menu par jour et par magasin),
pas au niveau **PRODUIT** / SKU.

### Entraînement

Depuis `backend/` :

```bash
python -m scripts.train_model
```

Notes :
- Le script tente d'abord de lire la view SQL `v_ventes_jour_menu`.
- Si la view n'existe pas, il bascule automatiquement sur une agrégation depuis la table `vente`.
- Les encoders sont basés sur les IDs (plus stable que les noms).

### Inference / génération des prédictions

```bash
python -m scripts.predict_sales --horizon 7
```

Options utiles :
- `--start-date YYYY-MM-DD`
- `--dry-run`

### API interne

Routes (protégées par `verifier_acces_interne`) :

#### Besoins ingrédients futurs

`GET /api/interne/previsions/besoins?magasin_id=...&date_debut=YYYY-MM-DD&date_fin=YYYY-MM-DD`

Retourne des lignes par jour/ingrédient :

- `quantite = somme(qte_predite(menu, jour) * ligne_recette.quantite)`

#### Alertes stock (ruptures / surstocks)

`GET /api/interne/previsions/alertes?magasin_id=...&date_debut=YYYY-MM-DD&date_fin=YYYY-MM-DD&seuil_surstock_ratio=2.0`

MVP :
- `stock_estime` = somme signée des `mouvement_stock` du magasin
- `besoin_total` = somme des besoins sur la fenêtre
- rupture si `stock_estime < besoin_total`
- surstock si `stock_estime > besoin_total * seuil_surstock_ratio`

## Cycle métier: Production du jour (backend only)

Le cycle "production du jour" existe comme service métier déterministe (sans API dédiée).

Fichier:
- `app/domaine/services/production_jour_service.py`

### Usage (exemple)

```python
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.services.production_jour_service import (
    ServiceProductionJour,
    LigneProductionJour,
)

async def run(session: AsyncSession, magasin_id: UUID):
    svc = ServiceProductionJour(session)
    res = await svc.executer_production_du_jour(
        magasin_id=magasin_id,
        date_jour=date.today(),
        lignes=[
            LigneProductionJour(recette_id=UUID("..."), quantite_a_produire=10),
            LigneProductionJour(recette_id=UUID("..."), quantite_a_produire=5),
        ],
    )
    return res
```

Règles garanties:
- atomicité : si un ingrédient manque → rollback (pas de lots, pas de consommations)
- FEFO : consommations via `ServiceExecutionProduction` / `AllocateurFEFO`
- historisation :
  - prévu: `PlanProduction` + `LignePlanProduction`
  - produit: `LotProduction` + `LigneConsommation` + `MouvementStock`

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
