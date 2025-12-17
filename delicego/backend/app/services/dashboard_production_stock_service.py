from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Final
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.production import LotProduction
from app.domaine.modeles.referentiel import Ingredient, Recette
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock


@dataclass(frozen=True)
class ProductionRecetteDuJour:
    recette_id: UUID
    recette_nom: str
    quantite_produite: float


@dataclass(frozen=True)
class ProductionDuJour:
    nombre_lots: int
    quantites_par_recette: list[ProductionRecetteDuJour]


@dataclass(frozen=True)
class ConsommationIngredientDuJour:
    ingredient_id: UUID
    ingredient_nom: str
    quantite_consommee: float


@dataclass(frozen=True)
class StockIngredientCourant:
    ingredient_id: UUID
    ingredient_nom: str
    stock_total: float


@dataclass(frozen=True)
class AlerteStockBas:
    ingredient_id: UUID
    ingredient_nom: str
    stock_total: float


@dataclass(frozen=True)
class AlerteDLC:
    ingredient_id: UUID
    ingredient_nom: str
    date_dlc: date


@dataclass(frozen=True)
class AlertesDashboard:
    stocks_bas: list[AlerteStockBas]
    dlc: list[AlerteDLC]


@dataclass(frozen=True)
class DashboardProductionStock:
    date_cible: date
    production: ProductionDuJour
    consommation: list[ConsommationIngredientDuJour]
    stock: list[StockIngredientCourant]
    alertes: AlertesDashboard


class DashboardProductionStockService:
    """Dashboard production / stock (V1 opérationnel).

    Contraintes :
    - lecture seule
    - agrégations simples
    - aucun import FastAPI
    - aucune écriture DB

    Périmètre V1 :
    - production du jour : nb lots + quantités produites par recette
    - consommation du jour : quantités consommées par ingrédient (uniquement via MouvementStock)
    - stock courant : stock total par ingrédient, calculé via (réception - consommation) uniquement
    - alertes : stock bas (<= seuil) et DLC dépassée (<= date_cible)
    """

    SEUIL_STOCK_MIN: Final[float] = 2.0

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lire(self, *, date_cible: date) -> DashboardProductionStock:
        debut = datetime.combine(date_cible, time.min).replace(tzinfo=timezone.utc)
        fin = datetime.combine(date_cible, time.max).replace(tzinfo=timezone.utc)

        production = await self._production_du_jour(debut=debut, fin=fin)
        consommation = await self._consommation_du_jour(debut=debut, fin=fin)
        stock = await self._stock_courant()
        alertes = await self._alertes(date_cible=date_cible, stock=stock)

        return DashboardProductionStock(
            date_cible=date_cible,
            production=production,
            consommation=consommation,
            stock=stock,
            alertes=alertes,
        )

    async def _production_du_jour(self, *, debut: datetime, fin: datetime) -> ProductionDuJour:
        res_nb = await self._session.execute(
            select(func.count(LotProduction.id)).where(LotProduction.produit_le >= debut, LotProduction.produit_le <= fin)
        )
        nombre_lots = int(res_nb.scalar_one() or 0)

        res_par_recette = await self._session.execute(
            select(
                Recette.id,
                Recette.nom,
                func.coalesce(func.sum(LotProduction.quantite_produite), 0.0).label("quantite"),
            )
            .select_from(LotProduction)
            .join(Recette, Recette.id == LotProduction.recette_id)
            .where(LotProduction.produit_le >= debut, LotProduction.produit_le <= fin)
            .group_by(Recette.id, Recette.nom)
            .order_by(Recette.nom.asc())
        )

        lignes = [
            ProductionRecetteDuJour(recette_id=r_id, recette_nom=str(nom), quantite_produite=float(qte or 0.0))
            for r_id, nom, qte in res_par_recette.all()
        ]

        return ProductionDuJour(nombre_lots=nombre_lots, quantites_par_recette=lignes)

    async def _consommation_du_jour(self, *, debut: datetime, fin: datetime) -> list[ConsommationIngredientDuJour]:
        res = await self._session.execute(
            select(
                Ingredient.id,
                Ingredient.nom,
                func.coalesce(func.sum(MouvementStock.quantite), 0.0).label("quantite"),
            )
            .select_from(MouvementStock)
            .join(Ingredient, Ingredient.id == MouvementStock.ingredient_id)
            .where(
                MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION,
                MouvementStock.horodatage >= debut,
                MouvementStock.horodatage <= fin,
            )
            .group_by(Ingredient.id, Ingredient.nom)
            .order_by(Ingredient.nom.asc())
        )

        return [
            ConsommationIngredientDuJour(
                ingredient_id=ing_id,
                ingredient_nom=str(nom),
                quantite_consommee=float(qte or 0.0),
            )
            for ing_id, nom, qte in res.all()
        ]

    async def _stock_courant(self) -> list[StockIngredientCourant]:
        # Stock = RECEPTION - CONSOMMATION uniquement.
        signe = case(
            (MouvementStock.type_mouvement == TypeMouvementStock.RECEPTION, 1),
            (MouvementStock.type_mouvement == TypeMouvementStock.CONSOMMATION, -1),
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
            .order_by(Ingredient.nom.asc())
        )

        return [
            StockIngredientCourant(
                ingredient_id=ing_id,
                ingredient_nom=str(nom),
                stock_total=float(stock or 0.0),
            )
            for ing_id, nom, stock in res.all()
        ]

    async def _alertes(
        self,
        *,
        date_cible: date,
        stock: list[StockIngredientCourant],
    ) -> AlertesDashboard:
        stocks_bas = [
            AlerteStockBas(
                ingredient_id=s.ingredient_id,
                ingredient_nom=s.ingredient_nom,
                stock_total=s.stock_total,
            )
            for s in stock
            if s.stock_total <= self.SEUIL_STOCK_MIN
        ]

        res_dlc = await self._session.execute(
            select(
                Lot.ingredient_id,
                Ingredient.nom,
                func.min(Lot.date_dlc).label("date_dlc"),
            )
            .select_from(Lot)
            .join(Ingredient, Ingredient.id == Lot.ingredient_id)
            .where(Lot.date_dlc.is_not(None), Lot.date_dlc <= date_cible)
            .group_by(Lot.ingredient_id, Ingredient.nom)
            .order_by(Ingredient.nom.asc())
        )

        dlc = [
            AlerteDLC(ingredient_id=ing_id, ingredient_nom=str(nom), date_dlc=dlc_date)
            for ing_id, nom, dlc_date in res_dlc.all()
            if dlc_date is not None
        ]

        return AlertesDashboard(stocks_bas=stocks_bas, dlc=dlc)
