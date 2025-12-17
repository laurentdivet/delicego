# Comparaison point par point — Écran Cuisine (Delicego vs Inpulse)

> Source Inpulse : captures fournies dans le chat.
> 
> Contrainte : backend **gelé** (API existante), couche UI minimale.

## 1) Navigation / accès

### Inpulse
- Menu latéral (icônes), accès direct au module.

### Delicego (actuel)
- Sidebar (texte) : entrée **Cuisine**.
- Route : `/cuisine`.

✅ OK (accès présent)

## 2) Filtre magasin + date

### Inpulse
- Sélecteur magasin (dropdown)
- Sélecteur date (range ou jour)

### Delicego (actuel)
- Champ texte `magasin_id (UUID)`
- Champ `date` (jour)

⚠️ Différence
- Inpulse : ergonomie magasin (dropdown) + contexte (nom magasin)
- Delicego : saisie UUID manuelle (MVP)

## 3) Lecture “à produire aujourd’hui”

### Inpulse
- Liste de produits/recettes avec quantités et statuts

### Delicego (actuel)
- Liste `cuisine[]` :
  - `recette_nom`
  - `quantite_planifiee`, `quantite_produite`
  - `statut` (A_PRODUIRE / PRODUIT / AJUSTE / NON_PRODUIT)

✅ OK (données et affichage)

## 4) Actions opérateur (Produit / Ajusté / Non produit)

### Inpulse
- Actions directement sur chaque ligne

### Delicego (actuel)
- Boutons par ligne :
  - **Produit** (POST `/api/interne/production-preparation/produit`)
  - **Ajusté** (prompt quantité) (POST `/ajuste`)
  - **Non produit** (POST `/non-produit`)

✅ OK (actions présentes)
⚠️ Différence UX
- Inpulse : quantité ajustée via UI intégrée
- Delicego : `prompt()` minimal

## 5) Traçabilité post-service

### Inpulse
- Consultation des actions réalisées / historique

### Delicego (actuel)
- Panneau Traçabilité :
  - bouton **Traçabilité** par recette
  - GET `/api/interne/production-preparation/traceabilite`
  - liste d’événements : type, date_heure, quantite, lot_production_id

✅ OK (traçabilité lisible)

## 6) Restes / éléments Inpulse non couverts (UI)

- Sélecteur magasin ergonomique (liste des magasins)
- Gestion multi-créneaux affichée (nous ne l’affichons pas côté UI, même si l’API renvoie `quantites_par_creneau`)
- Indicateurs visuels avancés (couleurs/graphes/contraintes)

➡️ Hors MVP UI actuel.
