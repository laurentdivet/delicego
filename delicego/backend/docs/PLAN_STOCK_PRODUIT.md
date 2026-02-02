# PLAN — Migration douce stock → `produit_id`

Objectif : basculer progressivement l’écriture et la lecture “stock réel” sur le **produit acheté** (`produit_id`) sans casser l’existant qui repose sur `ingredient_id`.

Principes :

- **Compatibilité d’abord** : on ajoute `produit_id` **nullable** et on ne supprime rien.
- **Idempotence** : scripts de backfill relançables (`--dry-run`, `--apply`, `--force`).
- **Double écriture** (quand possible) : lors des écritures stock, remplir `ingredient_id` (comme aujourd’hui) + `produit_id` si déductible.
- **Bascule progressive** ultérieure : rendre `produit_id` obligatoire seulement après couverture et monitoring.

## Phase A — Compatibilité (DB)

### Cible de cette itération (1–3 tables max)

Tables les plus critiques (“stock réel”) :

1. `mouvement_stock`
2. `lot`

### Changements

- Ajouter `produit_id` nullable sur ces tables.
- Ajouter FK `produit_id -> produit.id`.
- Ajouter index `ix_<table>_produit_id`.
- **Ne rien supprimer**, ne pas rendre obligatoire.

> Note sur `lot` : il existe une contrainte unique `uq_lot_magasin_ingredient_fournisseur_code`.
> Dans cette phase, on **ne la modifie pas**, pour minimiser les risques. (Une évolution future pourrait introduire une contrainte équivalente basée sur `produit_id`.)

## Phase B — Backfill (script)

Script : `backend/scripts/backfill_produit_id_stock.py`

Objectif : remplir `produit_id` **quand vide** à partir de `ingredient_id` via `ingredient.produit_id`.

Règles :

- Ne touche que les lignes où `produit_id IS NULL` (sauf `--force`).
- Si `ingredient.produit_id IS NULL` : ne remplit pas (report “impossible”).
- Supporter :
  - `--dry-run` : calcule/affiche sans commit
  - `--apply` : commit
  - `--force` : écrase `produit_id` existant (à manier avec précaution)
- Rapport :
  - nb candidats
  - nb backfill
  - nb impossibles

Tables backfillées dans cette itération :

- `lot`
- `mouvement_stock`

## Phase C — Double écriture (code)

Objectif : lors des écritures “stock réel”, écrire `produit_id` en plus de `ingredient_id` lorsque possible.

### Flux principal identifié

1) **Réception commande fournisseur** : `ServiceCommandeFournisseur.receptionner_commande()`

- À la création du `Lot` :
  - `ingredient_id` (comme aujourd’hui)
  - `produit_id = Ingredient.produit_id` si non-null

- À la création du `MouvementStock` :
  - `ingredient_id` (comme aujourd’hui)
  - `produit_id = Ingredient.produit_id` si non-null

2) **Consommation production** : `executer_production.py`

- Même logique : si `ingredient_id` a un produit associé, écrire `produit_id`.

> Dans cette itération, on garde une adaptation **minimale** sur le flux le plus clair.

## Phase D — Bascule progressive (hors scope de cette itération)

Pré-requis avant de rendre `produit_id` obligatoire :

- Backfill complet + monitoring (taux de NULL par table)
- Double écriture active sur tous les points d’entrée d’écriture stock (réception, consommation, transferts, ajustements…)
- Migration des requêtes de lecture critiques vers `produit_id` (ou fallback sur `ingredient_id`)

Ensuite seulement :

- Rendre `produit_id` `NOT NULL` table par table
- Éventuellement déprécier `ingredient_id` sur certaines tables (pas toutes)
