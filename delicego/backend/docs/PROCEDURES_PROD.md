# Procédures PROD — DéliceGo

Objectif : garde-fous minimum pour une exploitation en conditions réelles.

## Pré-requis

- PostgreSQL accessible (local, VM, Docker…)
- Outils installés côté machine qui exécute les scripts :
  - `pg_dump`, `pg_restore`, `psql`
  - `gzip`, `shasum`

## Variables d’environnement DB

Les scripts utilisent les variables standard Postgres :

```bash
export PGHOST=localhost
export PGPORT=5433
export PGUSER=delicego
export PGPASSWORD='delicego'
export PGDATABASE=delicego
```

## Backup PostgreSQL (automatisé)

Script : `backend/scripts/prod/backup_postgres.sh`

### Exécution manuelle

Depuis la racine du repo :

```bash
./backend/scripts/prod/backup_postgres.sh --keep 14
```

Sorties :
- dumps : `./backups/postgres/*.dump.gz`
- checksums : `./backups/postgres/*.dump.gz.sha256`

### Automatisation (cron)

Exemple : `backend/scripts/prod/backup_cron_example.txt`

Principe recommandé :
- rediriger stdout/stderr vers un fichier log dédié
- stocker `PGPASSWORD` dans un fichier protégé (ex: `/etc/delicego.env`, chmod 600)

## Restore PostgreSQL (testé)

Script : `backend/scripts/prod/restore_postgres.sh`

### Restore “sur place” (destructif)

```bash
./backend/scripts/prod/restore_postgres.sh \
  --file ./backups/postgres/delicego_delicego_YYYYMMDDTHHMMSSZ.dump.gz \
  --drop-create
```

### Restore vers une DB de test

```bash
./backend/scripts/prod/restore_postgres.sh \
  --file ./backups/postgres/delicego_delicego_YYYYMMDDTHHMMSSZ.dump.gz \
  --target-db delicego_restore_test \
  --drop-create
```

### Validation rapide post-restore

```bash
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d delicego_restore_test -c "\\dt" 
```

## Logs métiers (clés)

### Backend API

Un logging minimal est configuré au démarrage (`LOG_LEVEL`, stdout) :

- fichier : `backend/app/core/logging_config.py`
- appelé dans : `backend/app/main.py`

### Événements loggés

- Production du jour : `backend/app/domaine/services/production_jour_service.py`
  - `production_jour_start`
  - `production_jour_lot_create`
  - `production_jour_stock_insuffisant` (warning)
  - `production_jour_erreur` (exception)

- Production préparation (écran cuisine / scan / actions) : `backend/app/api/endpoints/production_preparation.py`
  - `production_preparation_*`

- Import recettes PDF : `backend/scripts/import_recettes_from_pdfs.py`
  - `import_recettes_from_pdfs_start`

- Remap lignes importées : `backend/app/domaine/services/remap_lignes_recette_importees.py`
  - `remap_start` / `remap_done`

## Gestion d’erreurs critiques (rollback + message clair)

### Principe

- Les services métier importants utilisent déjà `async with session.begin()`.
- En cas d’exception, SQLAlchemy rollback automatiquement.

### Wrapping utilitaire

Fichier : `backend/app/core/transactions.py`

- `executer_transaction(session, action=...)`
- `ErreurCritiqueMetier` pour remonter un message clair côté API.

## Checklist d’exploitation

1) Vérifier qu’un backup tourne (cron/launchd) et qu’un dump récent est présent
2) Tester une restauration (sur DB `*_restore_test`) au moins 1 fois / semaine
3) Vérifier les logs applicatifs (niveau INFO) lors des opérations clés (prod / import / remap)
