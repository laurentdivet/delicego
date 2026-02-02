# Notes Alembic — reproductibilité & stamping

## Pourquoi `alembic upgrade head` pouvait échouer (diagnostic)

Deux causes distinctes observées :

1) **Base locale “déjà peuplée” mais alembic non aligné**

- Symptomatique : `DuplicateTableError: relation "fournisseur" already exists` lors de l’exécution de `53582036ad5f_migration_initiale`.
- Cause : les tables existent, mais la table `alembic_version` ne reflète pas correctement l’état (ou la DB n’a jamais été migrée via Alembic).

2) **Migration non idempotente**

- Symptomatique (sur DB vierge) : `UndefinedObjectError` lors de `op.drop_constraint(...)` sur une contrainte qui n’existe pas.
- Cause : la migration `95429d51e3b7_fix_produit_fournisseur_constraints.py` supprimait une contrainte supposée exister.

## Correctifs apportés

1) **Migrations rendues idempotentes**

- `95429d51e3b7_fix_produit_fournisseur_constraints.py` : ne droppe la contrainte que si elle existe.
- `1e28a4774db8_add_produit_id_to_lot_and_mouvement_.py` : ajoute colonne/index/FK uniquement si absents.

2) **Surcharge d’URL DB pour tests/smoke**

- `backend/migrations/env.py` accepte désormais `DATABASE_URL` (env var) pour exécuter des migrations sur une DB cible.

## Procédure “propre” (stamping) — base locale uniquement

À utiliser **uniquement** quand :

- votre DB locale a déjà toutes (ou une partie) des tables créées hors Alembic,
- et vous voulez réaligner `alembic_version` sans rejouer les `CREATE TABLE`.

Commandes :

```bash
cd backend

# Voir l’état actuel
alembic current

# Marquer la DB comme étant déjà au head (ne crée rien)
alembic stamp head
```

⚠️ Attention : `stamp` ne modifie pas le schéma. Il ne fait que mettre à jour `alembic_version`.

## Preuve sur DB vierge (smoke)

On peut exécuter sur une DB fraîche :

```bash
cd backend

export DATABASE_URL='postgresql+asyncpg://delicego:delicego@localhost:5433/delicego_migration_smoke'
alembic -c alembic.ini upgrade head
```

Puis vérifier :

```bash
python -m scripts.backfill_produit_id_stock --dry-run
```

ou utiliser le script :

```bash
export DATABASE_URL='postgresql+asyncpg://delicego:delicego@localhost:5433/delicego_migration_smoke'
./scripts/smoke_migrations_produit_id.sh
```
