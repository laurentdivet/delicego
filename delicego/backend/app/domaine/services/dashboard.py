from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeClient, StatutPlanProduction, TypeMouvementStock
from app.domaine.modeles.commande_client import CommandeClient, LigneCommandeClient
from app.domaine.modeles.production import LignePlanProduction, LotProduction, PlanProduction
from app.domaine.modeles.referentiel import Ingredient
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock


# --- DTOs (retours simples, sérialisables) ---


@dataclass(frozen=True)
class DTOAlertesResume:
    stocks_bas: int
    lots_proches_dlc: int


@dataclass(frozen=True)
class DTOVueGlobale:
    date: date
    commandes_du_jour: int
    productions_du_jour: int
    quantite_produite: float
    alertes: DTOAlertesResume


@dataclass(frozen=True)
class DTOPlanProduction:
    id: UUID
    date_plan: date
    statut: StatutPlanProduction
    nombre_lignes: int


@dataclass(frozen=True)
class DTOCommandeClient:
    id: UUID
    date_commande: datetime
    statut: StatutCommandeClient
    nombre_lignes: int
    quantite_totale: float


@dataclass(frozen=True)
class DTOConsommationIngredient:
    ingredient_id: UUID
    ingredient: str
    quantite_consommee: float
    stock_estime: float
    lots_proches_dlc: int


@dataclass(frozen=True)
class DTOAlerteStockBas:
    ingredient_id: UUID
    ingredient: str
    stock_estime: float


@dataclass(frozen=True)
class DTOAlerteLotProcheDLC:
    ingredient_id: UUID
    ingredient: str
    date_dlc: date


@dataclass(frozen=True)
class DTOAlertesDetail:
    stocks_bas: list[DTOAlerteStockBas]
    lots_proches_dlc: list[DTOAlerteLotProcheDLC]


# --- Services lecture seule ---


class ServiceDashboardVueGlobale:
    """Agrégations globales du dashboard (lecture seule)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def obtenir_vue_globale(
        self,
        *,
        date_cible: date,
        seuil_stock_bas: float = 2.0,
        delai_dlc_jours: int = 2,
    ) -> DTOVueGlobale:
        debut = datetime.combine(date_cible, time.min).replace(tzinfo=timezone.utc)
        fin = datetime.combine(date_cible, time.max).replace(tzinfo=timezone.utc)

        # Commandes du jour
        res_cmd = await self._session.execute(
            select(func.count(CommandeClient.id)).where(
                CommandeClient.date_commande >= debut,
                CommandeClient.date_commande <= fin,
            )
        )
        commandes_du_jour = int(res_cmd.scalar_one())

        # Productions du jour (lots produits)
        res_prod = await self._session.execute(
            select(func.count(LotProduction.id), func.coalesce(func.sum(LotProduction.quantite_produite), 0.0)).where(
                LotProduction.produit_le >= debut,
                LotProduction.produit_le <= fin,
            )
        )
        productions_du_jour, quantite_produite = res_prod.one()

        service_alertes = ServiceDashboardStock(self._session)
        alertes = await service_alertes.obtenir_resume_alertes(
            date_cible=date_cible,
            seuil_stock_bas=seuil_stock_bas,
            delai_dlc_jours=delai_dlc_jours,
        )

        return DTOVueGlobale(
            date=date_cible,
            commandes_du_jour=commandes_du_jour,
            productions_du_jour=int(productions_du_jour or 0),
            quantite_produite=float(quantite_produite or 0.0),
            alertes=alertes,
        )


class ServiceDashboardProduction:
    """Lecture des plans de production (lecture seule)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lister_plans_production(self) -> list[DTOPlanProduction]:
        # Nb de lignes par plan
        res = await self._session.execute(
            select(
                PlanProduction.id,
                PlanProduction.date_plan,
                PlanProduction.statut,
                func.count(LignePlanProduction.id).label("nb_lignes"),
            )
            .select_from(PlanProduction)
            .outerjoin(
                LignePlanProduction,
                LignePlanProduction.plan_production_id == PlanProduction.id,
            )
            .group_by(PlanProduction.id)
            .order_by(PlanProduction.date_plan.desc())
        )

        plans: list[DTOPlanProduction] = []
        for pid, dplan, statut, nb_lignes in res.all():
            plans.append(
                DTOPlanProduction(
                    id=pid,
                    date_plan=dplan,
                    statut=statut,
                    nombre_lignes=int(nb_lignes or 0),
                )
            )
        return plans


class ServiceDashboardCommandes:
    """Lecture des commandes clients (lecture seule)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lister_commandes_clients(
        self,
        *,
        date_cible: date | None = None,
        statut: StatutCommandeClient | None = None,
    ) -> list[DTOCommandeClient]:
        conditions = []
        if date_cible is not None:
            debut = datetime.combine(date_cible, time.min).replace(tzinfo=timezone.utc)
            fin = datetime.combine(date_cible, time.max).replace(tzinfo=timezone.utc)
            conditions.extend([CommandeClient.date_commande >= debut, CommandeClient.date_commande <= fin])
        if statut is not None:
            conditions.append(CommandeClient.statut == statut)

        res = await self._session.execute(
            select(
                CommandeClient.id,
                CommandeClient.date_commande,
                CommandeClient.statut,
                func.count(LigneCommandeClient.id).label("nb_lignes"),
                func.coalesce(func.sum(LigneCommandeClient.quantite), 0.0).label("quantite_totale"),
            )
            .select_from(CommandeClient)
            .outerjoin(LigneCommandeClient, LigneCommandeClient.commande_client_id == CommandeClient.id)
            .where(*conditions)
            .group_by(CommandeClient.id)
            .order_by(CommandeClient.date_commande.desc())
        )

        commandes: list[DTOCommandeClient] = []
        for cid, dcmd, st, nb_lignes, qtot in res.all():
            commandes.append(
                DTOCommandeClient(
                    id=cid,
                    date_commande=dcmd,
                    statut=st,
                    nombre_lignes=int(nb_lignes or 0),
                    quantite_totale=float(qtot or 0.0),
                )
            )
        return commandes


class ServiceDashboardStock:
    """Agrégations consommation / stock / alertes (lecture seule)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def obtenir_resume_alertes(
        self,
        *,
        date_cible: date,
        seuil_stock_bas: float,
        delai_dlc_jours: int,
    ) -> DTOAlertesResume:
        alertes = await self.obtenir_alertes(
            date_cible=date_cible,
            seuil_stock_bas=seuil_stock_bas,
            delai_dlc_jours=delai_dlc_jours,
        )
        return DTOAlertesResume(
            stocks_bas=len(alertes.stocks_bas),
            lots_proches_dlc=len(alertes.lots_proches_dlc),
        )

    async def obtenir_alertes(
        self,
        *,
        date_cible: date,
        seuil_stock_bas: float = 2.0,
        delai_dlc_jours: int = 2,
    ) -> DTOAlertesDetail:
        stocks = await self._calculer_stock_estime_par_ingredient()

        stocks_bas: list[DTOAlerteStockBas] = []
        for ing_id, (nom, stock) in stocks.items():
            if stock < seuil_stock_bas:
                stocks_bas.append(DTOAlerteStockBas(ingredient_id=ing_id, ingredient=nom, stock_estime=stock))

        dlc_limite = date_cible.toordinal() + delai_dlc_jours

        res_lots = await self._session.execute(
            select(Lot.ingredient_id, Ingredient.nom, Lot.date_dlc)
            .select_from(Lot)
            .join(Ingredient, Ingredient.id == Lot.ingredient_id)
            .where(Lot.date_dlc.is_not(None))
        )

        lots_proches: list[DTOAlerteLotProcheDLC] = []
        for ing_id, nom, dlc in res_lots.all():
            if dlc is None:
                continue
            if dlc.toordinal() <= dlc_limite:
                lots_proches.append(DTOAlerteLotProcheDLC(ingredient_id=ing_id, ingredient=str(nom), date_dlc=dlc))

        # Tri stable
        lots_proches = sorted(lots_proches, key=lambda x: (x.date_dlc, x.ingredient))
        stocks_bas = sorted(stocks_bas, key=lambda x: (x.stock_estime, x.ingredient))

        return DTOAlertesDetail(stocks_bas=stocks_bas, lots_proches_dlc=lots_proches)

    async def obtenir_consommation(
        self,
        *,
        date_debut: date,
        date_fin: date,
        date_reference_dlc: date | None = None,
        delai_dlc_jours: int = 2,
    ) -> list[DTOConsommationIngredient]:
        """Retourne consommation + stock estimé + lots proches DLC.

        - Consommation : mouvements de type CONSOMMATION sur la période.
        - Stock : somme signée de tous les mouvements (jamais stocké en base).
        - Lots proches DLC : lots avec date_dlc <= date_reference_dlc + delai_dlc_jours.
        """

        debut = datetime.combine(date_debut, time.min).replace(tzinfo=timezone.utc)
        fin = datetime.combine(date_fin, time.max).replace(tzinfo=timezone.utc)

        # Sous-requête : consommation par ingrédient sur la période
        sous_conso = (
            select(
                MouvementStock.ingredient_id.label("ingredient_id"),
                func.coalesce(func.sum(MouvementStock.quantite), 0.0).label("quantite_consommee"),
            )
            .where(
                MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION,
                MouvementStock.horodatage >= debut,
                MouvementStock.horodatage <= fin,
            )
            .group_by(MouvementStock.ingredient_id)
            .subquery()
        )

        res = await self._session.execute(
            select(
                Ingredient.id,
                Ingredient.nom,
                func.coalesce(sous_conso.c.quantite_consommee, 0.0),
            )
            .select_from(Ingredient)
            .outerjoin(sous_conso, sous_conso.c.ingredient_id == Ingredient.id)
            .order_by(Ingredient.nom.asc())
        )

        # Stock estimé (global)
        signe = case(
            (MouvementStock.type_mouvement.in_([TypeMouvementStock.RECEPTION, TypeMouvementStock.AJUSTEMENT, TypeMouvementStock.TRANSFERT]), 1),
            (MouvementStock.type_mouvement.in_([TypeMouvementStock.CONSOMMATION, TypeMouvementStock.PERTE]), -1),
            else_=0,
        )
        stocks = await self._calculer_stock_estime_par_ingredient(signe=signe)

        # Lots proches DLC (compte)
        if date_reference_dlc is None:
            date_reference_dlc = date_fin
        dlc_limite = date_reference_dlc.toordinal() + int(delai_dlc_jours)

        # Compter uniquement ceux proches
        res_lots_proches = await self._session.execute(
            select(Lot.ingredient_id, Lot.date_dlc).where(Lot.date_dlc.is_not(None))
        )
        nb_proches: dict[UUID, int] = {}
        for ing_id, dlc in res_lots_proches.all():
            if dlc is None:
                continue
            if dlc.toordinal() <= dlc_limite:
                nb_proches[ing_id] = nb_proches.get(ing_id, 0) + 1

        resultats: list[DTOConsommationIngredient] = []
        for ing_id, nom, qcons in res.all():
            stock = stocks.get(ing_id, (str(nom), 0.0))[1]
            resultats.append(
                DTOConsommationIngredient(
                    ingredient_id=ing_id,
                    ingredient=str(nom),
                    quantite_consommee=float(qcons or 0.0),
                    stock_estime=float(stock),
                    lots_proches_dlc=int(nb_proches.get(ing_id, 0)),
                )
            )

        return resultats

    async def _calculer_stock_estime_par_ingredient(
        self,
        *,
        signe=None,
    ) -> dict[UUID, tuple[str, float]]:
        if signe is None:
            signe = case(
                (MouvementStock.type_mouvement.in_([TypeMouvementStock.RECEPTION, TypeMouvementStock.AJUSTEMENT, TypeMouvementStock.TRANSFERT]), 1),
                (MouvementStock.type_mouvement.in_([TypeMouvementStock.CONSOMMATION, TypeMouvementStock.PERTE]), -1),
                else_=0,
            )

        res = await self._session.execute(
            select(
                Ingredient.id,
                Ingredient.nom,
                func.coalesce(func.sum(signe * MouvementStock.quantite), 0.0).label("stock"),
            )
            .select_from(Ingredient)
            .outerjoin(MouvementStock, MouvementStock.ingredient_id == Ingredient.id)
            .group_by(Ingredient.id)
        )

        stocks: dict[UUID, tuple[str, float]] = {}
        for ing_id, nom, stock in res.all():
            stocks[ing_id] = (str(nom), float(stock or 0.0))
        return stocks
