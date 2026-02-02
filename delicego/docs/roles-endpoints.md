## Contrôle de rôles (API interne)

Objectif : rendre effectifs les rôles `admin` / `operateur` sur les routes sensibles.

### Politique

- **admin** : accès à toutes les routes internes.
- **operateur** :
  - production du jour (exécution) : **OK**
  - production préparation / scan : **OK**
  - lecture besoins (plan réel) : **OK**
  - tout le reste “production” (planifier/exécuter technique, créer plan réel, …) : **403**

### Exemples curl

Pré-requis : disposer d’un token JWT et le mettre dans `$TOKEN`.

#### 403 (pas le rôle requis)

Exemple : opérateur sur un endpoint **admin only** (`POST /api/interne/production/planifier`)

```bash
curl -i -X POST "http://localhost:8000/api/interne/production/planifier" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"magasin_id":"00000000-0000-0000-0000-000000000000","date_plan":"2026-02-02","date_debut_historique":"2026-01-01","date_fin_historique":"2026-02-01","donnees_meteo":null,"evenements":[]}'
```

Attendu : `HTTP/1.1 403`.

#### 200 (avec rôle)

Exemple : opérateur sur un endpoint autorisé (`POST /api/interne/operations/production-du-jour`)

```bash
curl -i -X POST "http://localhost:8000/api/interne/operations/production-du-jour" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"magasin_id":"00000000-0000-0000-0000-000000000000","date":"2026-02-02"}'
```

Attendu : `HTTP/1.1 200`.
