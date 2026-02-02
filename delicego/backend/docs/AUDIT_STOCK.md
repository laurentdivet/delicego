# AUDIT — Stock / Achats : migration douce vers `produit_id`

Objectif : préparer une bascule progressive du stock (lots, mouvements, réceptions) vers le **produit acheté** (`produit_id`) tout en conservant la compatibilité avec l’existant basé sur `ingredient_id`.

> Règle absolue : **pas de refonte brutale**, migration en phases, champs ajoutés **nullable**, backfill quand possible.

## A) Audit DB (tables “stock réel” / achats / réception)

### Synthèse

Aujourd’hui, les tables “stock réel” sont basées sur `ingredient_id` :

- `lot`
- `mouvement_stock`

Les tables “réception/achats” qui relient stock et achats sont aussi basées sur `ingredient_id` :

- `reception_marchandise`
- `ligne_reception_marchandise`
- `commande_achat`
- `ligne_commande_achat`
- `commande_fournisseur`
- `ligne_commande_fournisseur`

Le “stock réel” (quantités) est **uniquement** dérivé de `mouvement_stock` (immuable) + liens éventuels vers `lot`.

### Détails par table (colonnes / contraintes / indexes / volumes)

> Volumes observés sur la base locale au moment de l’audit : **0** lignes sur toutes ces tables.
> (Les volumes seront à re-mesurer en prod/staging.)

| Table | Colonnes d’identification produit | FK existantes | Index/uniq notables | Remarque | Action (Phase A) |
|---|---|---|---|---|---|
| `mouvement_stock` | `ingredient_id` (NOT NULL), **pas de `produit_id`** | FK `ingredient_id -> ingredient.id`, `lot_id -> lot.id`, `magasin_id -> magasin.id` | `ix_mouvement_stock_horodatage`, `ix_mouvement_stock_lot_id`, `ix_mouvement_stock_type` | Table centrale (stock immuable) | **Ajouter `produit_id` nullable + FK + index** |
| `lot` | `ingredient_id` (NOT NULL), **pas de `produit_id`** | FK `ingredient_id -> ingredient.id`, `magasin_id -> magasin.id`, `fournisseur_id -> fournisseur.id` | uniq `uq_lot_magasin_ingredient_fournisseur_code`, index `ix_lot_date_dlc` | Les lots sont FEFO via date_dlc | **Ajouter `produit_id` nullable + FK + index** (attention à la contrainte unique actuelle) |
| `reception_marchandise` | aucune (`magasin_id`, `fournisseur_id`, `commande_achat_id`) | FK vers `commande_achat`, `fournisseur`, `magasin` | `ix_reception_marchandise_recu_le` | Entête réception | (hors scope Phase A) |
| `ligne_reception_marchandise` | `ingredient_id` (NOT NULL), **pas de `produit_id`** | FK `ingredient_id -> ingredient.id`, `lot_id -> lot.id`, `mouvement_stock_id -> mouvement_stock.id`, `reception_marchandise_id -> reception_marchandise.id` | (PK seule) | Ligne de réception (peut pointer lot et mouvement) | (hors scope Phase A) |
| `commande_achat` | aucune | FK `magasin_id -> magasin.id`, `fournisseur_id -> fournisseur.id` | `ix_commande_achat_creee_le` | Achat (structure) | (hors scope Phase A) |
| `ligne_commande_achat` | `ingredient_id` (NOT NULL), **pas de `produit_id`** | FK `commande_achat_id -> commande_achat.id`, `ingredient_id -> ingredient.id` | (PK seule) | Lignes d’achats “techniques” | (hors scope Phase A) |
| `commande_fournisseur` | aucune | FK `fournisseur_id -> fournisseur.id` | `ix_commande_fournisseur_date_commande` | Commande fournisseur métier | (hors scope Phase A) |
| `ligne_commande_fournisseur` | `ingredient_id` (NOT NULL), **pas de `produit_id`** | FK `commande_fournisseur_id -> commande_fournisseur.id`, `ingredient_id -> ingredient.id` | (PK seule) | Ligne commande fournisseur (réception partielle possible) | (hors scope Phase A) |

## B) Audit code (écriture stock / usages)

### Modèles (DB)

- `backend/app/domaine/modeles/stock_tracabilite.py`
  - `Lot` : `ingredient_id` obligatoire
  - `MouvementStock` : `ingredient_id` obligatoire

- `backend/app/domaine/modeles/achats.py`
  - `LigneReceptionMarchandise` : `ingredient_id` obligatoire
  - `LigneCommandeAchat` : `ingredient_id` obligatoire
  - `LigneCommandeFournisseur` : `ingredient_id` obligatoire

### Points d’entrée principaux d’écriture stock

1) **Réception commande fournisseur**

- Fichier : `backend/app/domaine/services/commander_fournisseur.py`
- Méthode : `ServiceCommandeFournisseur.receptionner_commande()`
- Écritures :
  - création `Lot(magasin_id, ingredient_id, fournisseur_id, ...)`
  - création `MouvementStock(type=RECEPTION, magasin_id, ingredient_id, lot_id, quantite, ...)`
  - update `LigneCommandeFournisseur.quantite_recue`

2) **Exécution production (consommation)**

- Fichier : `backend/app/domaine/services/executer_production.py`
- Écritures :
  - création `MouvementStock(type=CONSOMMATION, magasin_id, ingredient_id, lot_id, ...)`
  - création `LigneConsommation` (production)

### Où le domaine parle déjà de `produit_id`

- Aujourd’hui, le stock/achats est très largement sur `ingredient_id`.
- `produit_id` existe au niveau du référentiel (`Ingredient.produit_id`) et du catalogue (`Produit`, `ProduitFournisseur`), mais pas encore dans les tables stock/achats.
