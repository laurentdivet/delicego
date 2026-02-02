from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.stock_tracabilite import MouvementStock
from app.services.previsions_besoins_service import PrevisionsBesoinsService


@dataclass(frozen=True)
class AlerteRupturePrevue:
    ingredient_id: UUID
    ingredient_nom: str
    unite: str
    stock_estime: float
    besoin_total: float
    delta: float  # stock - besoin


@dataclass(frozen=True)
class AlerteSurstockPrevu:
    ingredient_id: UUID
    ingredient_nom: str
    unite: str
    stock_estime: float
    besoin_total: float
    surplus: float  # stock - besoin


class PrevisionsAlertesStockService:
    """Alertes stock basées sur besoins futurs vs stock courant.

    MVP: compare le stock estimé (somme signée des mouvements) au besoin total sur la fenêtre.
    - rupture: stock < besoin_total
    - surstock: stock > besoin_total * seuil_surstock_ratio
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _stock_estime(
        self,
        *,
        magasin_id: UUID,
    ) -> dict[UUID, float]:
        signe = case(
            (
                MouvementStock.type_mouvement.in_(
                    [
                        TypeMouvementStock.RECEPTION,
                        TypeMouvementStock.AJUSTEMENT,
                        TypeMouvementStock.TRANSFERT,
                    ]
                ),
                1,
            ),
            (
                MouvementStock.type_mouvement.in_([
                    TypeMouvementStock.CONSOMMATION,
                    TypeMouvementStock.PERTE,
                ]),
                -1,
            ),
            else_=0,
        )

        res = await self._session.execute(
            select(
                MouvementStock.ingredient_id,
                func.coalesce(func.sum(signe * MouvementStock.quantite), 0.0).label("stock"),
            )
            .where(MouvementStock.magasin_id == magasin_id)
            .group_by(MouvementStock.ingredient_id)
        )
        return {ing_id: float(stock or 0.0) for ing_id, stock in res.all()}

    async def calculer_alertes(
        self,
        *,
        magasin_id: UUID,
        date_debut: date,
        date_fin: date,
        seuil_surstock_ratio: float = 2.0,
    ) -> tuple[list[AlerteRupturePrevue], list[AlerteSurstockPrevu]]:
        if seuil_surstock_ratio <= 1.0:
            raise ValueError("seuil_surstock_ratio doit être > 1.0")

        besoins = await PrevisionsBesoinsService(self._session).calculer_besoins(
            magasin_id=magasin_id,
            date_debut=date_debut,
            date_fin=date_fin,
        )

        # Agréger besoin total sur la fenêtre (par ingredient_id + unite)
        besoin_tot: dict[tuple[UUID, str, str], float] = {}
        for b in besoins:
            key = (b.ingredient_id, b.ingredient_nom, b.unite)
            besoin_tot[key] = besoin_tot.get(key, 0.0) + float(b.quantite)

        stocks = await self._stock_estime(magasin_id=magasin_id)

        ruptures: list[AlerteRupturePrevue] = []
        surstocks: list[AlerteSurstockPrevu] = []

        for (ing_id, ing_nom, unite), bt in besoin_tot.items():
            stock = float(stocks.get(ing_id, 0.0))
            delta = stock - float(bt)

            if delta < 0:
                ruptures.append(
                    AlerteRupturePrevue(
                        ingredient_id=ing_id,
                        ingredient_nom=str(ing_nom),
                        unite=str(unite),
                        stock_estime=stock,
                        besoin_total=float(bt),
                        delta=float(delta),
                    )
                )
            elif float(bt) > 0 and stock > float(bt) * float(seuil_surstock_ratio):
                surstocks.append(
                    AlerteSurstockPrevu(
                        ingredient_id=ing_id,
                        ingredient_nom=str(ing_nom),
                        unite=str(unite),
                        stock_estime=stock,
                        besoin_total=float(bt),
                        surplus=float(delta),
                    )
                )

        ruptures = sorted(ruptures, key=lambda x: (x.delta, x.ingredient_nom))
        surstocks = sorted(surstocks, key=lambda x: (-x.surplus, x.ingredient_nom))
        return ruptures, surstocks
