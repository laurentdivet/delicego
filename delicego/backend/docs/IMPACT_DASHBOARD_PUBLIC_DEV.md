## IMPACT_DASHBOARD_PUBLIC_DEV (DEV-only)

Par défaut, le dashboard Impact **public** (consommé par l'UI `/impact`) n'est **pas** exposé.
Il est activable uniquement en développement via une variable d'environnement.

### Activation

Définir :

```bash
export IMPACT_DASHBOARD_PUBLIC_DEV=1
```

### Endpoints exposés (publics, DEV-only)

Sous `/api/impact/*` :

- `GET /api/impact/dashboard`
  - Retourne KPIs + recommandations + actions associées.
- `POST /api/impact/recommendations/{id}/actions`
  - Crée une action liée à une recommandation (status initial `OPEN`).
- `PATCH /api/impact/actions/{id}`
  - Met à jour `status` et/ou `description`.
- `PATCH /api/impact/recommendations/{id}`
  - Met à jour `status` et/ou `comment`.
  - Règle `resolved_at` :
    - si `status=RESOLVED` => `resolved_at` est renseigné si absent
    - sinon => `resolved_at` est remis à `NULL`

### Sécurité / Production

- Ces endpoints sont **guardés** par `IMPACT_DASHBOARD_PUBLIC_DEV`.
- En production (sans cette variable), ils répondent **403**.
- Aucun secret (clé interne) n'est nécessaire côté frontend.
