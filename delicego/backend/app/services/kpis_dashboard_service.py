from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.referentiel import Menu
from app.domaine.modeles.stock_tracabilite import MouvementStock
from app.domaine.modeles.ventes_prevision import ExecutionPrevision, LignePrevision


@dataclass(frozen=True)
class ValeurTendance:
    valeur: float
    variation_pct: float | None = None


@dataclass(frozen=True)
class KPIsInpulse:
    date_cible: date
    ca_jour: ValeurTendance
    ca_semaine: ValeurTendance
    ca_mois: ValeurTendance
    ecart_vs_prevision_pct: float | None
    food_cost_reel_pct: float | None
    marge_brute_eur: float | None
    marge_brute_pct: float | None
    pertes_gaspillage_eur: float | None
    ruptures_produits_nb: int
    ruptures_impact_eur: float | None
    heures_economisees: float | None


class KPIsDashboardService:
    """Calcul des KPI "Inpulse-like".

    Hypothèses MVP (faute de modèle POS complet) :
    - CA = somme(LigneCommandeClient.quantite * Menu.prix) sur commandes CONFIRMEE (tous magasins).
    - Prévision = somme(LignePrevision.quantite_prevue * Menu.prix) sur la date.
    - Food cost réel = (consommation + pertes) valorisées au prix matière (approx) / CA.
      Ici MVP : valorisation matière via Ingredient.cout_unitaire n'est pas joinée pour rester léger;
      on utilise Menu.prix * 0.3 comme proxy si besoin. (À remplacer quand on modélise coût matière réel.)
    - Ruptures = nb menus commandables mais indisponibles (ServiceDisponibiliteMenu) => ici proxy simplifié:
      nb menus inactifs/ non commandables = 0, donc on renvoie 0 en MVP.

    IMPORTANT: ce service est conçu pour être remplacé/étendu au fur et à mesure que
    l'on branche les sources POS et les coûts réels.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _variation_pct(valeur: float, reference: float) -> float | None:
        if reference <= 0:
            return None
        return ((valeur - reference) / reference) * 100.0

    async def calculer(self, *, date_cible: date, magasin_id: UUID | None = None) -> KPIsInpulse:
        ca_jour = await self._ca_sur_periode(date_cible, date_cible, magasin_id=magasin_id)

        # semaine ISO : du lundi au dimanche
        debut_semaine = date_cible - timedelta(days=date_cible.weekday())
        fin_semaine = debut_semaine + timedelta(days=6)
        ca_semaine = await self._ca_sur_periode(debut_semaine, fin_semaine, magasin_id=magasin_id)

        debut_mois = date(date_cible.year, date_cible.month, 1)
        if date_cible.month == 12:
            debut_mois_suiv = date(date_cible.year + 1, 1, 1)
        else:
            debut_mois_suiv = date(date_cible.year, date_cible.month + 1, 1)
        fin_mois = debut_mois_suiv - timedelta(days=1)
        ca_mois = await self._ca_sur_periode(debut_mois, fin_mois, magasin_id=magasin_id)

        # tendances (variation vs période précédente)
        ca_jour_prec = await self._ca_sur_periode(
            date_cible - timedelta(days=1),
            date_cible - timedelta(days=1),
            magasin_id=magasin_id,
        )
        ca_semaine_prec = await self._ca_sur_periode(
            debut_semaine - timedelta(days=7),
            fin_semaine - timedelta(days=7),
            magasin_id=magasin_id,
        )
        fin_mois_prec = debut_mois - timedelta(days=1)
        debut_mois_prec = date(fin_mois_prec.year, fin_mois_prec.month, 1)
        ca_mois_prec = await self._ca_sur_periode(
            debut_mois_prec,
            fin_mois_prec,
            magasin_id=magasin_id,
        )

        ecart_vs_prev = await self._ecart_vs_prevision_pct(date_cible=date_cible, magasin_id=magasin_id, ca_reel=ca_jour)

        # Food cost réel: MVP basé sur mouvements stock (CONSOMMATION + PERTE) mais sans coût unitaire => proxy.
        food_cost_pct, pertes_eur = await self._food_cost_et_pertes(date_cible=date_cible, magasin_id=magasin_id, ca_reel=ca_jour)

        marge_eur = None
        marge_pct = None
        if ca_jour > 0 and food_cost_pct is not None:
            # Marge brute = CA - coût matière
            cout_matiere = (food_cost_pct / 100.0) * ca_jour
            marge_eur = ca_jour - cout_matiere
            marge_pct = (marge_eur / ca_jour) * 100.0 if ca_jour > 0 else None

        # Ruptures : MVP = 0 (à brancher avec disponibilité + impact)
        ruptures_nb = 0
        ruptures_impact = None

        # Heures économisées : placeholder
        heures_economisees = None

        return KPIsInpulse(
            date_cible=date_cible,
            ca_jour=ValeurTendance(valeur=ca_jour, variation_pct=self._variation_pct(ca_jour, ca_jour_prec)),
            ca_semaine=ValeurTendance(valeur=ca_semaine, variation_pct=self._variation_pct(ca_semaine, ca_semaine_prec)),
            ca_mois=ValeurTendance(valeur=ca_mois, variation_pct=self._variation_pct(ca_mois, ca_mois_prec)),
            ecart_vs_prevision_pct=ecart_vs_prev,
            food_cost_reel_pct=food_cost_pct,
            marge_brute_eur=marge_eur,
            marge_brute_pct=marge_pct,
            pertes_gaspillage_eur=pertes_eur,
            ruptures_produits_nb=ruptures_nb,
            ruptures_impact_eur=ruptures_impact,
            heures_economisees=heures_economisees,
        )

    async def _ca_sur_periode(self, debut: date, fin: date, *, magasin_id: UUID | None) -> float:
        debut_dt = datetime.combine(debut, datetime.min.time()).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(fin, datetime.max.time()).replace(tzinfo=timezone.utc)

        q = (
            select(func.coalesce(func.sum(LigneCommandeClient.quantite * Menu.prix), 0.0))
            .select_from(LigneCommandeClient)
            .join(CommandeClient, CommandeClient.id == LigneCommandeClient.commande_client_id)
            .join(Menu, Menu.id == LigneCommandeClient.menu_id)
            .where(CommandeClient.date_commande >= debut_dt, CommandeClient.date_commande <= fin_dt)
        )
        if magasin_id is not None:
            q = q.where(CommandeClient.magasin_id == magasin_id)

        res = await self._session.execute(q)
        return float(res.scalar_one() or 0.0)

    async def _ecart_vs_prevision_pct(self, *, date_cible: date, magasin_id: UUID | None, ca_reel: float) -> float | None:
        # Prévision = somme(quantite_prevue * Menu.prix) sur la date
        q = (
            select(func.coalesce(func.sum(LignePrevision.quantite_prevue * Menu.prix), 0.0))
            .select_from(LignePrevision)
            .join(Menu, Menu.id == LignePrevision.menu_id)
            .join(ExecutionPrevision, ExecutionPrevision.id == LignePrevision.execution_prevision_id)
            .where(LignePrevision.date_prevue == date_cible)
        )
        if magasin_id is not None:
            q = q.where(ExecutionPrevision.magasin_id == magasin_id)

        res = await self._session.execute(q)
        prev = float(res.scalar_one() or 0.0)
        if prev <= 0:
            return None
        return ((ca_reel - prev) / prev) * 100.0

    async def _food_cost_et_pertes(self, *, date_cible: date, magasin_id: UUID | None, ca_reel: float) -> tuple[float | None, float | None]:
        debut_dt = datetime.combine(date_cible, datetime.min.time()).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(date_cible, datetime.max.time()).replace(tzinfo=timezone.utc)

        # Proxy valorisation matière: on valorise quantité consommée à 1€ (pour avoir une valeur non nulle)
        # TODO: remplacer par Ingredient.cout_unitaire et conversions d'unité.
        signe_perte = case(
            (MouvementStock.type_mouvement == TypeMouvementStock.PERTE, 1),
            else_=0,
        )

        q = (
            select(
                func.coalesce(func.sum(MouvementStock.quantite), 0.0).label("qte"),
                func.coalesce(func.sum(signe_perte * MouvementStock.quantite), 0.0).label("perte_qte"),
            )
            .select_from(MouvementStock)
            .where(
                MouvementStock.horodatage >= debut_dt,
                MouvementStock.horodatage <= fin_dt,
                MouvementStock.type_mouvement.in_([TypeMouvementStock.CONSOMMATION, TypeMouvementStock.PERTE]),
            )
        )
        if magasin_id is not None:
            q = q.where(MouvementStock.magasin_id == magasin_id)

        res = await self._session.execute(q)
        qte, perte_qte = res.one()

        cout_matiere_eur = float(qte or 0.0) * 1.0
        pertes_eur = float(perte_qte or 0.0) * 1.0

        if ca_reel <= 0:
            return None, pertes_eur

        return (cout_matiere_eur / ca_reel) * 100.0, pertes_eur
