-- =========================================
-- PLAN DE PRODUCTION -> CONSOMMATION DU JOUR
-- Upsert + Nettoyage + Contrôles
-- =========================================

-- 1) UPSERT des consommations calculées (idempotent)
WITH upsert AS (
  INSERT INTO ligne_consommation (
      lot_production_id,
      ingredient_id,
      quantite,
      unite
  )
  SELECT
      lp.id AS lot_production_id,
      lr.ingredient_id,
      (lp.quantite_produite * lr.quantite)::double precision AS quantite,
      lr.unite
  FROM lot_production lp
  JOIN ligne_recette lr ON lr.recette_id = lp.recette_id
  WHERE lp.produit_jour = current_date
  ON CONFLICT (lot_production_id, ingredient_id)
  DO UPDATE SET
      quantite      = EXCLUDED.quantite,
      unite         = EXCLUDED.unite,
      mis_a_jour_le = now()
  RETURNING (xmax = 0) AS inserted
)
SELECT
  count(*) FILTER (WHERE inserted)     AS lignes_inserees,
  count(*) FILTER (WHERE NOT inserted) AS lignes_mises_a_jour
FROM upsert;

-- 2) NETTOYAGE : supprime les consommations obsolètes (ingrédient retiré de la recette)
DELETE FROM ligne_consommation lc
USING lot_production lp
WHERE lc.lot_production_id = lp.id
  AND lp.produit_jour = current_date
  AND NOT EXISTS (
    SELECT 1
    FROM ligne_recette lr
    WHERE lr.recette_id = lp.recette_id
      AND lr.ingredient_id = lc.ingredient_id
  );

-- 3) CONTRÔLES
SELECT count(*) AS lots_du_jour
FROM lot_production
WHERE produit_jour = current_date;

SELECT count(*) AS conso_du_jour
FROM ligne_consommation lc
JOIN lot_production lp ON lp.id = lc.lot_production_id
WHERE lp.produit_jour = current_date;
