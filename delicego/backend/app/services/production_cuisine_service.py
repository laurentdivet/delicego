from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import CanalVente
from app.domaine.modeles.production import LignePlanProduction, LotProduction, PlanProduction
from app.domaine.modeles.referentiel import Menu, Recette
from app.domaine.modeles.ventes_prevision import Vente


class ErreurProductionCuisine(Exception):
    pass


@dataclass(frozen=True)
class Creneau:
    code: str
    libelle: str
    heure_debut: int
    heure_fin_incluse: int


CRENEAUX: list[Creneau] = [
    Creneau(code="MATIN", libelle="Matin", heure_debut=6, heure_fin_incluse=10),
    Creneau(code="MIDI", libelle="Midi", heure_debut=11, heure_fin_incluse=15),
    Creneau(code="SOIR", libelle="Soir", heure_debut=16, heure_fin_incluse=22),
]


@dataclass(frozen=True)
class LigneCuisine:
    recette_id: UUID
    recette_nom: str
    quantite_planifiee: float
    quantite_produite: float
    dernier_lot_production_id: UUID | None
    dernier_lot_quantite: float | None
    dernier_lot_produit_le: datetime | None


@dataclass(frozen=True)
class KPICuisine:
    date_plan: date
    plan_production_id: UUID
    magasin_id: UUID
    quantite_totale_a_produire: float
    quantite_totale_produite: float
    quantite_restante: float
    quantites_par_creneau: dict[str, float]


class ServiceProductionCuisine:
    """Lecture/écriture opérationnelle pour l'écran cuisine.

    Principes MVP :
    - La *traçabilité* est assurée via `LotProduction`.
    - Les actions "Produit" / "Ajusté" / "Non produit" créent un `LotProduction`.
      - quantite_produite == 0 => considéré comme "NON_PRODUIT".
    - Le statut visible dans l'UI est dérivé du *dernier* lot (dernier produit_le).

    NOTE : on ne modifie pas le schéma SQL (pas de nouveau champ statut), on reste compatible.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def trouver_plan(self, *, magasin_id: UUID, date_plan: date) -> PlanProduction:
        res = await self._session.execute(
            select(PlanProduction).where(
                PlanProduction.magasin_id == magasin_id,
                PlanProduction.date_plan == date_plan,
            )
        )
        plan = res.scalar_one_or_none()
        if plan is None:
            raise ErreurProductionCuisine("PlanProduction introuvable pour ce magasin et cette date.")
        return plan

    async def lire_lignes(self, *, plan_production_id: UUID) -> list[LigneCuisine]:
        """Lit les lignes planifiées pour l'écran cuisine.

        Transition safe (menu_id):
        - Si `ligne_plan_production.menu_id` est présent => on affiche `menu.nom`.
        - Sinon fallback via `recette_id` dans le magasin du plan.
          Pour éviter toute duplication (recette présente dans plusieurs menus du magasin),
          on résout via une sous-requête déterministe (min(menu.nom)).
        - Si aucune résolution menu possible => fallback = `recette.nom`.

        Requête de contrôle ambiguïtés (debug/ops):
        SELECT magasin_id, recette_id, count(*) FROM menu GROUP BY 1,2 HAVING count(*)>1;
        """

        # Sous-requête fallback: pour chaque recette dans un magasin, un nom de menu déterministe.
        menu_nom_par_recette_magasin = (
            select(
                Menu.magasin_id.label("magasin_id"),
                Menu.recette_id.label("recette_id"),
                func.min(Menu.nom).label("menu_nom"),
            )
            .group_by(Menu.magasin_id, Menu.recette_id)
            .subquery()
        )

        # Lignes planifiées + nom affiché "safe" (menu si possible, sinon recette)
        # - JOIN plan -> magasin_id
        # - JOIN recette
        # - LEFT JOIN menu direct via menu_id
        # - LEFT JOIN fallback via (magasin_id, recette_id)
        res = await self._session.execute(
            select(
                LignePlanProduction.recette_id,
                case(
                    (Menu.nom.is_not(None), Menu.nom),
                    (menu_nom_par_recette_magasin.c.menu_nom.is_not(None), menu_nom_par_recette_magasin.c.menu_nom),
                    else_=Recette.nom,
                ).label("libelle"),
                LignePlanProduction.quantite_a_produire,
            )
            .select_from(LignePlanProduction)
            .join(PlanProduction, PlanProduction.id == LignePlanProduction.plan_production_id)
            .join(Recette, Recette.id == LignePlanProduction.recette_id)
            .outerjoin(Menu, Menu.id == LignePlanProduction.menu_id)
            .outerjoin(
                menu_nom_par_recette_magasin,
                (menu_nom_par_recette_magasin.c.magasin_id == PlanProduction.magasin_id)
                & (menu_nom_par_recette_magasin.c.recette_id == LignePlanProduction.recette_id),
            )
            .where(LignePlanProduction.plan_production_id == plan_production_id)
            .order_by(
                case(
                    (Menu.nom.is_not(None), Menu.nom),
                    (menu_nom_par_recette_magasin.c.menu_nom.is_not(None), menu_nom_par_recette_magasin.c.menu_nom),
                    else_=Recette.nom,
                ).asc()
            )
        )
        base = [(rid, str(lib), float(q or 0.0)) for rid, lib, q in res.all()]

        # Quantité produite cumulée par recette (lots)
        res_prod = await self._session.execute(
            select(
                LotProduction.recette_id,
                func.coalesce(func.sum(LotProduction.quantite_produite), 0.0).label("qte"),
            )
            .select_from(LotProduction)
            .where(LotProduction.plan_production_id == plan_production_id)
            .group_by(LotProduction.recette_id)
        )
        prod_par_recette: dict[UUID, float] = {rid: float(q or 0.0) for rid, q in res_prod.all()}

        # Dernier lot par recette (pour statut)
        res_last = await self._session.execute(
            select(
                LotProduction.recette_id,
                LotProduction.id,
                LotProduction.quantite_produite,
                LotProduction.produit_le,
            )
            .select_from(LotProduction)
            .where(LotProduction.plan_production_id == plan_production_id)
            .order_by(LotProduction.recette_id.asc(), LotProduction.produit_le.desc())
        )
        last: dict[UUID, tuple[UUID, float, datetime]] = {}
        for rid, lid, q, ts in res_last.all():
            if rid in last:
                continue
            if lid is None or ts is None:
                continue
            last[rid] = (lid, float(q or 0.0), ts)

        lignes: list[LigneCuisine] = []
        for rid, nom, q_plan in base:
            lid = last.get(rid, (None, None, None))[0]
            lq = last.get(rid, (None, None, None))[1]
            lts = last.get(rid, (None, None, None))[2]
            lignes.append(
                LigneCuisine(
                    recette_id=rid,
                    recette_nom=nom,
                    quantite_planifiee=q_plan,
                    quantite_produite=float(prod_par_recette.get(rid, 0.0)),
                    dernier_lot_production_id=lid,
                    dernier_lot_quantite=lq,
                    dernier_lot_produit_le=lts,
                )
            )

        return lignes

    async def calculer_kpis(self, *, plan: PlanProduction) -> KPICuisine:
        lignes = await self.lire_lignes(plan_production_id=plan.id)
        total_plan = sum(l.quantite_planifiee for l in lignes)
        total_prod = sum(l.quantite_produite for l in lignes)
        restante = max(0.0, float(total_plan - total_prod))

        # Répartition par créneau: basée sur la distribution horaire des ventes du jour (réel) (ou uniforme si pas de ventes).
        debut_dt = datetime.combine(plan.date_plan, time.min).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(plan.date_plan, time.max).replace(tzinfo=timezone.utc)

        q = (
            select(
                func.extract("hour", Vente.date_vente).label("h"),
                func.coalesce(func.sum(Vente.quantite), 0.0).label("qte"),
            )
            .select_from(Vente)
            .where(
                Vente.magasin_id == plan.magasin_id,
                Vente.date_vente >= debut_dt,
                Vente.date_vente <= fin_dt,
                Vente.canal.in_([CanalVente.INTERNE, CanalVente.EXTERNE, CanalVente.AUTRE]),
            )
            .group_by("h")
        )
        rows = (await self._session.execute(q)).all()
        reel_par_heure: dict[int, float] = {int(h): float(q or 0.0) for h, q in rows if h is not None}
        total_reel = sum(reel_par_heure.values())

        poids_par_heure: dict[int, float] = {}
        for h in range(24):
            if total_reel > 0:
                poids_par_heure[h] = reel_par_heure.get(h, 0.0) / total_reel
            else:
                poids_par_heure[h] = 1.0 / 24.0

        par_creneau: dict[str, float] = {c.code: 0.0 for c in CRENEAUX}
        for c in CRENEAUX:
            poids = sum(poids_par_heure[h] for h in range(c.heure_debut, c.heure_fin_incluse + 1))
            par_creneau[c.code] = float(total_plan) * float(poids)

        return KPICuisine(
            date_plan=plan.date_plan,
            plan_production_id=plan.id,
            magasin_id=plan.magasin_id,
            quantite_totale_a_produire=float(total_plan),
            quantite_totale_produite=float(total_prod),
            quantite_restante=float(restante),
            quantites_par_creneau=par_creneau,
        )

    async def creer_lot(self, *, plan: PlanProduction, recette_id: UUID, quantite: float, unite: str = "unite") -> LotProduction:
        if quantite is None or float(quantite) < 0:
            raise ErreurProductionCuisine("La quantité doit être >= 0")

        lot = LotProduction(
            magasin_id=plan.magasin_id,
            plan_production_id=plan.id,
            recette_id=recette_id,
            quantite_produite=float(quantite),
            unite=str(unite),
        )
        self._session.add(lot)
        await self._session.flush()
        return lot

    @staticmethod
    def statut_ligne(*, quantite_planifiee: float, quantite_produite: float, dernier_lot_quantite: float | None) -> str:
        if dernier_lot_quantite is not None and float(dernier_lot_quantite) <= 0:
            return "NON_PRODUIT"
        if quantite_produite <= 0:
            return "A_PRODUIRE"
        if quantite_produite + 1e-6 >= quantite_planifiee:
            return "PRODUIT"
        return "AJUSTE"
