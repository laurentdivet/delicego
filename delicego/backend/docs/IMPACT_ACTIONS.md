# Impact Actions (reco → actions)

Ce document décrit les **actions** associées aux recommandations de l’Impact Dashboard.

## Modèle

Une action est liée à une recommandation.

Champs principaux :

- `id` (uuid)
- `recommendation_id` (uuid)
- `action_type` (enum) — ex: `MANUAL`
- `status` (enum) — ex: `OPEN`, `DONE`
- `description` (str)

Champs "exploitables" ajoutés :

- `assignee` (str | null) : responsable (ex: "Bob")
- `due_date` (date | null) : échéance
- `priority` (int | null) : 1 = haute, 5 = basse (convention UI)
- `updated_at` (datetime) : mis à jour à chaque modification (PATCH)

## API interne (auth token)

Ces endpoints sont derrière le token interne (`INTERNAL_API_TOKEN`).

### Dashboard (KPIs + recos + actions)

```bash
curl -s \
  -H 'Authorization: Bearer <INTERNAL_API_TOKEN>' \
  'http://localhost:8000/api/interne/impact/dashboard?days=30&limit=50'
```

### Créer une action

```bash
curl -s -X POST \
  -H 'Authorization: Bearer <INTERNAL_API_TOKEN>' \
  -H 'Content-Type: application/json' \
  'http://localhost:8000/api/interne/impact/recommendations/<RECO_ID>/actions' \
  -d '{
    "action_type": "MANUAL",
    "description": "Appeler le manager",
    "assignee": "Bob",
    "due_date": "2030-02-01",
    "priority": 2
  }'
```

### Mettre à jour une action (PATCH)

```bash
curl -s -X PATCH \
  -H 'Authorization: Bearer <INTERNAL_API_TOKEN>' \
  -H 'Content-Type: application/json' \
  'http://localhost:8000/api/interne/impact/actions/<ACTION_ID>' \
  -d '{
    "status": "DONE",
    "description": "Fait",
    "assignee": "Alice",
    "due_date": "2030-02-15",
    "priority": 1
  }'
```

Retour : l’action complète, avec `updated_at` modifié.

## Export CSV (interne)

Endpoint :

`GET /api/interne/impact/export/actions.csv`

Exemple :

```bash
curl -s \
  -H 'Authorization: Bearer <INTERNAL_API_TOKEN>' \
  'http://localhost:8000/api/interne/impact/export/actions.csv?days=365' \
  -o impact-actions.csv
```

Colonnes (en-tête CSV) :

```
magasin,reco_code,reco_status,reco_severity,action_id,action_status,priority,due_date,assignee,description,created_at,updated_at,occurrences,last_seen_at
```

Notes :

- Le CSV est encodé en UTF-8.
- Les dates/datetimes sont sérialisées au format ISO.

## Tests

Deux smoke tests existent (et nécessitent une DB via `DATABASE_URL`) :

- `backend/tests/test_impact_actions_smoke.py`
- `backend/tests/test_impact_actions_export_csv_smoke.py`

Pour lancer :

```bash
export DATABASE_URL='postgresql+asyncpg://user:pass@localhost:5432/dbname'
cd backend
pytest -q tests/test_impact_actions_smoke.py tests/test_impact_actions_export_csv_smoke.py
```
