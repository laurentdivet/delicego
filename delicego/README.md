# DéliceGo

## Dev — one command

### Prérequis

- Docker (avec `docker compose`)
- Node.js (recommandé: >= 20.19)

### Lancer l'environnement de dev

Depuis la racine du dépôt :

```bash
./scripts/dev.sh
```

Le script :

- démarre PostgreSQL via Docker Compose
- attend que Postgres soit prêt
- **reset** la base `delicego` (drop/create)
- applique les migrations Alembic + exécute les seeds
- lance backend + frontend en parallèle (arrêt propre au Ctrl+C)

### Ports

- Backend : http://localhost:8001
- Frontend : http://localhost:5173
- Postgres : localhost:5433
