# Impact KPIs (Étape 4)

Objectif : fournir des KPI exploitables **côté backend** (DB + API) pour suivre :

- **Gaspillage / pertes**
- **Part du local**
- **Estimation CO2e**

Ces KPI sont **MVP** : cohérents et traçables, mais pas "scientifiquement parfaits".

## Endpoints (read-only)

Routes internes (header `X-CLE-INTERNE`).

- `GET /api/interne/impact/summary?days=30`
- `GET /api/interne/impact/waste?days=30`
- `GET /api/interne/impact/local?days=30&local_km_threshold=100`
- `GET /api/interne/impact/co2?days=30`

## Dashboard Impact (pilotage quotidien)

Endpoints dashboard (KPIs + reco/actions) :

- Interne (protégé Bearer): `GET /api/interne/impact/dashboard?days=30&limit=200`
- Public (DEV-only): `GET /api/impact/dashboard?days=30&limit=200`

### Filtrage multi-magasins

Paramètre optionnel : `magasin_id` (UUID).

- si `magasin_id` est fourni : KPIs + recommandations/actions sont filtrées sur ce magasin
- sinon : comportement global (tous magasins)

### Filtres / tri côté serveur (recommandations)

Paramètres optionnels :

- `status`: `OPEN|ACKNOWLEDGED|RESOLVED`
- `severity`: `LOW|MEDIUM|HIGH`
- `sort`: `last_seen_desc` (défaut) ou `occurrences_desc`
- `limit`: déjà présent (défaut 200)

### Endpoint magasins (pour l'UI)

- `GET /api/interne/magasins` (protégé Bearer)
- Retour: `[{id, nom}]`

Chaque endpoint renvoie un JSON stable avec :

- des agrégats (`value`)
- des séries temporelles journalières simples (`[{date, value}]`)

## KPI : définitions

### 1) `kpi_waste_rate`

**Définition :**

`waste_rate = pertes / (réception + production)` sur la période.

**MVP implémenté :**

- `pertes` = somme des mouvements stock `PERTE` + table `perte_casse` (si utilisée)
- `(réception + production)` = somme des mouvements stock `RECEPTION` + `CONSOMMATION`
  - ici `CONSOMMATION` sert de proxy "production" (faute de modèle complet de production en kg)

> Note : pas de conversion d'unités en MVP. Il faut rester cohérent dans les quantités (ex : tout en kg).

### 2) `kpi_local_share`

**Définition :** part des achats "locaux".

**MVP implémenté :**

- `achats` = nombre de `reception_marchandise` sur la période
- `local` = fournisseur avec `distance_km <= seuil`

Si `distance_km` est NULL : le fournisseur est considéré non-local.

### 3) `kpi_co2_estimate`

**Définition :** somme des émissions sur la période.

**MVP implémenté :**

- base = mouvements stock `RECEPTION`
- mapping `ingredient -> categorie` via `ingredient_impact.categorie_co2`
- facteur = `facteur_co2.facteur_kgco2e_par_kg`

Formule : `kgCO2e = somme(quantite * facteur_kgco2e_par_kg)`

> IMPORTANT : valeurs indicatives par défaut uniquement. Remplacer par vos valeurs réelles.

### 4) (Optionnel) `kpi_savings_vs_baseline`

`/impact/summary` peut inclure `include_savings_vs_baseline=true`.

Cela renvoie un delta simple vs la période précédente (même durée).

## Configuration

### Seuil local

Variable d'env : `IMPACT_LOCAL_KM_THRESHOLD` (float).

Par défaut : `100.0`.

Dans le code : `ParametresApplication.impact_local_km_threshold`.

### Facteurs CO2

Stockage DB : table `facteur_co2`.

- colonne `categorie` (clé)
- colonne `facteur_kgco2e_par_kg`
- colonne `source` (traçabilité)

Mapping ingredient -> catégorie : table `ingredient_impact`.

## Seed démo

Le script `backend/scripts/seed_demo.py` ajoute :

- 2 fournisseurs (local/non-local) avec `distance_km`
- des réceptions `reception_marchandise` pour calculer `local_share`
- 1 mouvement stock `PERTE` + 1 ligne `perte_casse`
- 2 facteurs CO2 indicatifs (viande, légumes) + mapping de l'ingrédient démo

## Exemples curl

```bash
curl -H 'X-CLE-INTERNE: cle-technique' 'http://localhost:8000/api/interne/impact/summary?days=30'
curl -H 'X-CLE-INTERNE: cle-technique' 'http://localhost:8000/api/interne/impact/waste?days=30'
curl -H 'X-CLE-INTERNE: cle-technique' 'http://localhost:8000/api/interne/impact/local?days=30&local_km_threshold=100'
curl -H 'X-CLE-INTERNE: cle-technique' 'http://localhost:8000/api/interne/impact/co2?days=30'

# Dashboard interne
curl -H 'Authorization: Bearer <token>' 'http://localhost:8000/api/interne/impact/dashboard?days=30&limit=200'

# Dashboard interne filtré magasin + filtres reco
curl -H 'Authorization: Bearer <token>' \
  'http://localhost:8000/api/interne/impact/dashboard?days=30&limit=200&magasin_id=<uuid>&status=OPEN&severity=HIGH&sort=occurrences_desc'

# Liste magasins (interne)
curl -H 'Authorization: Bearer <token>' 'http://localhost:8000/api/interne/magasins'
```
