from __future__ import annotations

"""Services HACCP / PMS.

Objectif : fournir une base exploitable pour des contrôles sanitaires réels.

Ce module ne fait **aucun** effet de bord automatique :
- Il expose des fonctions déterministes (lecture DB) pour détecter des anomalies.
- La génération de NonConformiteHACCP est explicite via `generer_non_conformites`.

Règles implémentées (minimales mais extensibles) :
- Températures : compare le dernier relevé par équipement avec [temperature_min, temperature_max].
- DLC : détecte les lots dont la DLC est dépassée (date_dlc < aujourd’hui) et qui ont encore du stock > 0.

"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import TypeMouvementStock
from app.domaine.modeles.hygiene import EquipementThermique, NonConformiteHACCP, ReleveTemperature
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock


@dataclass(frozen=True)
class AnomalieTemperature:
    magasin_id: UUID
    equipement_id: UUID
    releve_id: UUID
    temperature: float
    min_autorisee: float | None
    max_autorisee: float | None


@dataclass(frozen=True)
class AnomalieDLC:
    magasin_id: UUID
    lot_id: UUID
    ingredient_id: UUID
    date_dlc: date
    quantite_disponible: float
    unite: str


class ServiceHACCP:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def verifier_temperature(self) -> list[AnomalieTemperature]:
        """Retourne les anomalies de température (dernier relevé par équipement)."""

        # Dernier relevé par équipement (subquery)
        sub = (
            select(
                ReleveTemperature.equipement_thermique_id.label("eq_id"),
                func.max(ReleveTemperature.releve_le).label("max_dt"),
            )
            .group_by(ReleveTemperature.equipement_thermique_id)
            .subquery()
        )

        q = (
            select(ReleveTemperature, EquipementThermique)
            .join(sub, (sub.c.eq_id == ReleveTemperature.equipement_thermique_id) & (sub.c.max_dt == ReleveTemperature.releve_le))
            .join(EquipementThermique, EquipementThermique.id == ReleveTemperature.equipement_thermique_id)
            .where(EquipementThermique.actif.is_(True))
        )

        res = await self._session.execute(q)

        anomalies: list[AnomalieTemperature] = []
        for releve, equipement in res.all():
            t = float(releve.temperature)
            tmin = equipement.temperature_min
            tmax = equipement.temperature_max

            hors_min = tmin is not None and t < float(tmin)
            hors_max = tmax is not None and t > float(tmax)

            if hors_min or hors_max:
                anomalies.append(
                    AnomalieTemperature(
                        magasin_id=equipement.magasin_id,
                        equipement_id=equipement.id,
                        releve_id=releve.id,
                        temperature=t,
                        min_autorisee=tmin,
                        max_autorisee=tmax,
                    )
                )

        return anomalies

    async def verifier_dlc(self, *, aujourd_hui: date | None = None) -> list[AnomalieDLC]:
        """Retourne les anomalies DLC (lots périmés avec stock > 0)."""

        if aujourd_hui is None:
            aujourd_hui = date.today()

        # Convention signe (comme FEFO)
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
                MouvementStock.type_mouvement.in_(
                    [
                        TypeMouvementStock.CONSOMMATION,
                        TypeMouvementStock.PERTE,
                    ]
                ),
                -1,
            ),
            else_=0,
        )

        # Pour chaque lot périmé, calculer le solde et filtrer solde > 0
        q = (
            select(
                Lot.id,
                Lot.magasin_id,
                Lot.ingredient_id,
                Lot.date_dlc,
                Lot.unite,
                func.coalesce(func.sum(signe * MouvementStock.quantite), 0.0).label("solde"),
            )
            .join(MouvementStock, MouvementStock.lot_id == Lot.id)
            .where(Lot.date_dlc.is_not(None))
            .where(Lot.date_dlc < aujourd_hui)
            .group_by(Lot.id, Lot.magasin_id, Lot.ingredient_id, Lot.date_dlc, Lot.unite)
        )

        res = await self._session.execute(q)

        anomalies: list[AnomalieDLC] = []
        for lot_id, magasin_id, ingredient_id, dlc, unite, solde in res.all():
            solde_f = float(solde or 0.0)
            if solde_f > 1e-9 and dlc is not None:
                anomalies.append(
                    AnomalieDLC(
                        magasin_id=magasin_id,
                        lot_id=lot_id,
                        ingredient_id=ingredient_id,
                        date_dlc=dlc,
                        quantite_disponible=solde_f,
                        unite=str(unite),
                    )
                )

        return anomalies

    async def generer_non_conformites(self) -> list[UUID]:
        """Crée en base des NonConformiteHACCP pour les anomalies détectées.

        Retourne la liste des ids créés.
        """

        ids: list[UUID] = []

        anomalies_temp = await self.verifier_temperature()
        anomalies_dlc = await self.verifier_dlc()

        async with self._session.begin():
            for a in anomalies_temp:
                nc = NonConformiteHACCP(
                    magasin_id=a.magasin_id,
                    type_non_conformite="TEMP_HORS_SEUIL",
                    reference=str(a.equipement_id),
                    description=(
                        f"Température hors seuil: {a.temperature}°C (min={a.min_autorisee}, max={a.max_autorisee})"
                    ),
                    statut="OUVERTE",
                )
                self._session.add(nc)
                await self._session.flush()
                ids.append(nc.id)

            for a in anomalies_dlc:
                nc = NonConformiteHACCP(
                    magasin_id=a.magasin_id,
                    type_non_conformite="DLC_DEPASSEE",
                    reference=str(a.lot_id),
                    description=(
                        f"Lot périmé (DLC={a.date_dlc}) avec stock {a.quantite_disponible} {a.unite}"
                    ),
                    statut="OUVERTE",
                )
                self._session.add(nc)
                await self._session.flush()
                ids.append(nc.id)

        return ids
