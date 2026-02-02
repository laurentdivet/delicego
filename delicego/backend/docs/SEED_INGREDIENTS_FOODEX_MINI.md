# Seed — Ingrédients métiers (mini set) basés sur Foodex

Objectif : remplacer les ingrédients placeholders (type `ING*`) par un set **minimal** d’ingrédients métiers, **liés explicitement** à un `Produit` du catalogue via `ingredient.produit_id`.

## Ingrédients créés (seed_all)

Implémentation : `backend/scripts/seed_all.py`

### Produits Foodex utilisés comme base

Dans le catalogue Sorae importé (`PRODUITS_SORAE.xlsx`), les entrées les plus “génériques” disponibles pour nos tests sont :

- `RIZ VINAIGRE`
- `GINGEMBRE ROSE`

> Remarque : le seed **n’utilise aucun fallback**. Si le catalogue ne contient pas (encore)
> un produit explicite (ex: `SAUCE SOJA`, `WASABI`), alors `ingredient.produit_id` reste `NULL`.

### Ingrédients métiers (créés/activés)

#### Ingrédients mappés (produit_id NON NULL)

- `Riz sushi` → `RIZ VINAIGRE`
- `Vinaigre de riz` → `RIZ VINAIGRE`
- `Gingembre mariné` → `GINGEMBRE ROSE`

#### Ingrédients volontairement NON mappés (produit_id = NULL)

- `Sauce soja` → `NULL` *(pas de produit `SAUCE SOJA` dans le catalogue démo actuel)*
- `Wasabi` → `NULL` *(pas de produit `WASABI` dans le catalogue démo actuel)*

Champs renseignés quand possible :

- `ingredient.unite_consommation = 'g'`
- `ingredient.facteur_conversion = 1000.0` (achat en `kg` → consommation en `g`)

## Placeholders

Les ingrédients existants dont le nom matche `ING%` sont **désactivés** (`actif=false`) plutôt que supprimés, pour éviter de casser d’éventuelles FK.

## Commandes de vérification

Après import catalogue + seed :

```bash
cd backend

# Import catalogue (idempotent)
python -m scripts.import_catalogue_foodex_xlsx --xlsx ../PRODUITS_SORAE.xlsx --fournisseur-nom Foodex

# Seed global (idempotent)
python -m scripts.seed_all --apply --catalog-xlsx ../PRODUITS_SORAE.xlsx
```

Vérifier les ingrédients :

```sql
SELECT id, nom, actif, produit_id FROM ingredient ORDER BY nom;
```

Vérifier que chaque ingrédient de démo a un produit :

```sql
SELECT i.nom, p.libelle
FROM ingredient i
JOIN produit p ON p.id = i.produit_id
ORDER BY i.nom;

-- Lister ceux qui restent à mapper
SELECT id, nom
FROM ingredient
WHERE actif = true AND produit_id IS NULL
ORDER BY nom;
```
