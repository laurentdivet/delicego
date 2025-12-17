from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutPlanProduction
from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.modeles.referentiel import Menu, Recette
from app.domaine.modeles.ventes_prevision import Vente


class ErreurPlanificationProduction(Exception):
    """Erreur générique de planification."""


class PlanProductionDejaExistant(ErreurPlanificationProduction):
    """Un plan existe déjà pour (magasin, date_plan)."""


@dataclass(frozen=True)
class _ContexteAjustement:
    """Contexte exogène injecté au service.

    IMPORTANT :
    - Aucune récupération externe : tout est injecté.
    - Le service reste déterministe : mêmes entrées => même sortie.
    """

    donnees_meteo: dict[str, float]
    evenements: list[str]


class ServicePlanificationProduction:
    """Service de planification avancée de production.

    Objectif : générer un PlanProduction (BROUILLON) et ses LignePlanProduction à partir :
    - d’un historique de ventes sur une période
    - d’ajustements exogènes (météo, événements)

    Contraintes :
    - Ne modifie aucun modèle
    - N’expose aucune API HTTP
    - N’interagit pas avec les services FEFO ou Production
    - Tout le code est en français
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

        # Cache par instance (évite tout effet de bord entre tests / services).
        self._cache_noms_recettes: dict[UUID, str] = {}

        # Table simple d’ajustements par événements.
        # Facile à modifier/étendre sans réécrire l’algorithme.
        self._coefficients_evenements: dict[str, float] = {
            "LIGUE_DES_CHAMPIONS": 1.20,
            "MATCH_EQUIPE_DE_FRANCE": 1.20,
        }

        # Heuristique explicite (et donc testable) de classification des recettes.
        # NOTE : on n’a pas de champ “type” en base (contrainte : ne pas modifier les modèles).
        # On s’appuie donc sur le nom de la recette / menu.
        self._mots_cles_recettes_froides = {
            "salade",
            "bowl",
            "wrap",
            "froid",
        }
        self._mots_cles_recettes_snacking_partage = {
            "snack",
            "snacking",
            "partage",
            "apero",
            "apéro",
            "chips",
            "pizza",
            "nuggets",
        }

    async def planifier(
        self,
        *,
        magasin_id: UUID,
        date_plan: date,
        date_debut_historique: date,
        date_fin_historique: date,
        donnees_meteo: dict[str, float],
        evenements: list[str],
    ) -> PlanProduction:
        """Génère un plan de production.

        Règles :
        - Si un plan existe déjà pour (magasin, date) => exception.
        - Si aucune vente historique => plan vide mais valide.
        - Les quantités sont arrondies intelligemment et bornées à >= 0.
        """

        if date_fin_historique < date_debut_historique:
            raise ErreurPlanificationProduction(
                "La période historique est invalide : date_fin_historique < date_debut_historique."
            )

        contexte = _ContexteAjustement(donnees_meteo=donnees_meteo, evenements=evenements)

        async with self._session.begin():
            await self._verifier_absence_plan_existant(magasin_id=magasin_id, date_plan=date_plan)

            # 1) Base historique : moyenne journalière par recette
            moyenne_par_recette = await self._calculer_moyenne_journaliere_par_recette(
                magasin_id=magasin_id,
                date_debut_historique=date_debut_historique,
                date_fin_historique=date_fin_historique,
            )

            # Pré-charger les noms des recettes concernées.
            # Objectif : rendre la classification déterministe et éviter des requêtes dispersées.
            await self._charger_cache_noms_recettes(list(moyenne_par_recette.keys()))

            # 2/3) Ajustements exogènes
            quantites_finales = self._appliquer_ajustements(
                moyenne_par_recette=moyenne_par_recette,
                contexte=contexte,
            )

            # 4) Génération du plan
            plan = PlanProduction(
                magasin_id=magasin_id,
                date_plan=date_plan,
                statut=StatutPlanProduction.BROUILLON,
            )
            self._session.add(plan)
            await self._session.flush()  # obtenir plan.id

            for recette_id, quantite in sorted(quantites_finales.items(), key=lambda x: str(x[0])):
                # Quantité toujours >= 0, jamais NaN, et sans flottants “absurdes”.
                quantite = self._arrondir_intelligemment(max(0.0, float(quantite)))

                ligne = LignePlanProduction(
                    plan_production_id=plan.id,
                    recette_id=recette_id,
                    quantite_a_produire=quantite,
                )
                self._session.add(ligne)

            await self._session.flush()
            return plan

    async def _verifier_absence_plan_existant(self, *, magasin_id: UUID, date_plan: date) -> None:
        resultat = await self._session.execute(
            select(PlanProduction.id).where(
                PlanProduction.magasin_id == magasin_id,
                PlanProduction.date_plan == date_plan,
            )
        )
        deja = resultat.scalar_one_or_none()
        if deja is not None:
            raise PlanProductionDejaExistant(
                "Un PlanProduction existe déjà pour ce magasin et cette date."
            )

    async def _calculer_moyenne_journaliere_par_recette(
        self,
        *,
        magasin_id: UUID,
        date_debut_historique: date,
        date_fin_historique: date,
    ) -> dict[UUID, float]:
        """Agrège les ventes en quantités journalières par recette, puis calcule une moyenne.

        Hypothèses explicites :
        - Une vente est rattachée à un Menu.
        - Une Recette est rattachée à un Menu (1 recette par menu pour l’instant dans le modèle).
        - La quantité vendue est `Vente.quantite`.

        IMPORTANT :
        On calcule la moyenne sur le nombre de jours de la période (inclusif),
        pour rester déterministe (même si certains jours n’ont aucune vente).
        """

        nb_jours = (date_fin_historique - date_debut_historique).days + 1
        if nb_jours <= 0:
            return {}

        debut_dt = datetime.combine(date_debut_historique, time.min).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(date_fin_historique, time.max).replace(tzinfo=timezone.utc)

        # Total vendu par recette sur la période
        # Join : Vente -> Menu -> Recette (modèle Inpulse-like : menu -> recette)
        resultat = await self._session.execute(
            select(
                Recette.id.label("recette_id"),
                func.sum(Vente.quantite).label("quantite_totale"),
            )
            .select_from(Vente)
            .join(Menu, Menu.id == Vente.menu_id)
            .join(Recette, Recette.id == Menu.recette_id)
            .where(
                Vente.magasin_id == magasin_id,
                Vente.date_vente >= debut_dt,
                Vente.date_vente <= fin_dt,
            )
            .group_by(Recette.id)
        )

        moyenne_par_recette: dict[UUID, float] = {}
        for recette_id, quantite_totale in resultat.all():
            total = float(quantite_totale or 0.0)
            moyenne_par_recette[recette_id] = total / float(nb_jours)

        return moyenne_par_recette

    def _appliquer_ajustements(
        self,
        *,
        moyenne_par_recette: dict[UUID, float],
        contexte: _ContexteAjustement,
    ) -> dict[UUID, float]:
        """Applique les règles d’ajustement.

        Règles demandées (simples, explicites et modifiables) :

        Météo :
        - Si temperature_max >= 25°C : +15% sur recettes froides / salades
        - Si precipitations_mm > 5 : -10% sur les ventes globales

        Événements sportifs :
        - Si LIGUE_DES_CHAMPIONS ou MATCH_EQUIPE_DE_FRANCE : +20% sur recettes “snacking / partage”
        """

        temperature_max = float(contexte.donnees_meteo.get("temperature_max", 0.0) or 0.0)
        precipitations = float(contexte.donnees_meteo.get("precipitations_mm", 0.0) or 0.0)

        # Ajustement global (pluie)
        coefficient_global = 1.0
        if precipitations > 5.0:
            coefficient_global *= 0.90

        # Ajustement ciblé (chaleur)
        coefficient_froid = 1.0
        if temperature_max >= 25.0:
            coefficient_froid *= 1.15

        # Ajustement événementiel (sport)
        coefficient_snacking = 1.0
        for ev in contexte.evenements:
            if ev in self._coefficients_evenements:
                # On prend le produit des coefficients présents.
                coefficient_snacking *= float(self._coefficients_evenements[ev])

        # Application
        resultats: dict[UUID, float] = {}
        for recette_id, base in moyenne_par_recette.items():
            quantite = float(base)

            # Global d’abord
            quantite *= coefficient_global

            # Les règles suivantes dépendent du type de recette.
            if self._est_recette_froide(recette_id):
                quantite *= coefficient_froid

            if self._est_recette_snacking_partage(recette_id):
                quantite *= coefficient_snacking

            # Garde-fou : pas de négatif.
            if quantite < 0.0:
                quantite = 0.0

            resultats[recette_id] = quantite

        return resultats

    def _arrondir_intelligemment(self, valeur: float) -> float:
        """Arrondi pour éviter les flottants absurdes.

        Convention simple :
        - < 1 : on garde 2 décimales (ex : 0.33)
        - >= 1 : on arrondit à l’unité la plus proche

        Cela reste facilement modifiable si on décide plus tard d’une autre politique.
        """

        if valeur <= 0.0:
            return 0.0

        if valeur < 1.0:
            return float(round(valeur, 2))

        return float(int(round(valeur)))

    def _est_recette_froide(self, recette_id: UUID) -> bool:
        """Heuristique basée sur le nom (pas de champ type en base).

        IMPORTANT :
        Pour rester déterministe, on n’interroge pas la base ici.
        Les tests créent des recettes avec des noms explicites.
        """

        nom = self._cache_noms_recettes.get(recette_id)
        if nom is None:
            return False
        nom_normalise = nom.lower()
        return any(mot in nom_normalise for mot in self._mots_cles_recettes_froides)

    def _est_recette_snacking_partage(self, recette_id: UUID) -> bool:
        nom = self._cache_noms_recettes.get(recette_id)
        if nom is None:
            return False
        nom_normalise = nom.lower()
        return any(mot in nom_normalise for mot in self._mots_cles_recettes_snacking_partage)

    async def _charger_cache_noms_recettes(self, recette_ids: list[UUID]) -> None:
        """Charge les noms des recettes en une fois.

        NOTE : cette méthode n’est appelée qu’à l’intérieur de la transaction de planification.
        """

        if not recette_ids:
            return

        resultat = await self._session.execute(
            select(Recette.id, Recette.nom).where(Recette.id.in_(recette_ids))
        )
        for rid, nom in resultat.all():
            self._cache_noms_recettes[rid] = str(nom)
