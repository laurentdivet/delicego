from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.referentiel import Menu
from app.domaine.modeles.ventes_prevision import ExecutionPrevision, LignePrevision, Vente


@dataclass(frozen=True)
class PointHoraire:
    heure: int
    quantite_prevue: float
    quantite_reelle: float
    ca_prevu: float
    ca_reel: float


@dataclass(frozen=True)
class LigneProduit:
    menu_id: UUID
    menu_nom: str
    quantite_prevue: float
    quantite_reelle: float
    ca_prevu: float
    ca_reel: float


@dataclass(frozen=True)
class Fiabilite:
    wape_ca_pct: float | None
    mape_ca_pct: float | None
    fiabilite_ca_pct: float | None


@dataclass(frozen=True)
class PrevisionVentes:
    date_cible: date
    magasin_id: UUID | None
    ca_prevu: float
    ca_reel: float
    quantite_prevue: float
    quantite_reelle: float
    courbe_horaire: list[PointHoraire]
    table_produits: list[LigneProduit]
    fiabilite: Fiabilite


class PrevisionVentesService:
    """Agrégations "prévision des ventes".

    Données disponibles dans le modèle actuel :
    - Réel: table `Vente` (quantité + date_vente + menu_id + magasin_id)
    - Prévu: table `LignePrevision` (quantite_prevue + date_prevue + menu_id) liée à `ExecutionPrevision` (magasin_id)

    Limites MVP :
    - Prévision horaire : non stockée => on la dérive en répartissant la prévision journalière selon la distribution horaire
      observée sur les ventes réelles du jour (ou une distribution uniforme si pas de ventes).
    - Impacts météo / jour férié : non stockés => on expose des champs optionnels dans l'API mais on ne calcule rien ici.
    - Fiabilité modèle : calculée sur une fenêtre simple (N jours avant date_cible) sur le CA journalier.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def obtenir(
        self,
        *,
        date_cible: date,
        magasin_id: UUID | None,
        fenetre_fiabilite_jours: int = 14,
    ) -> PrevisionVentes:
        # Totaux et table produits
        produits = await self._prevision_vs_reel_par_produit(date_cible=date_cible, magasin_id=magasin_id)

        ca_prevu = sum(p.ca_prevu for p in produits)
        ca_reel = sum(p.ca_reel for p in produits)
        q_prevue = sum(p.quantite_prevue for p in produits)
        q_reelle = sum(p.quantite_reelle for p in produits)

        # Courbe horaire: dérivée
        courbe = await self._courbe_horaire(date_cible=date_cible, magasin_id=magasin_id, ca_prevu=ca_prevu, q_prevue=q_prevue)

        # Fiabilité
        fiabilite = await self._fiabilite_ca(
            date_cible=date_cible,
            magasin_id=magasin_id,
            fenetre_jours=fenetre_fiabilite_jours,
        )

        return PrevisionVentes(
            date_cible=date_cible,
            magasin_id=magasin_id,
            ca_prevu=ca_prevu,
            ca_reel=ca_reel,
            quantite_prevue=q_prevue,
            quantite_reelle=q_reelle,
            courbe_horaire=courbe,
            table_produits=produits,
            fiabilite=fiabilite,
        )

    async def _prevision_vs_reel_par_produit(self, *, date_cible: date, magasin_id: UUID | None) -> list[LigneProduit]:
        debut_dt = datetime.combine(date_cible, time.min).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(date_cible, time.max).replace(tzinfo=timezone.utc)

        # Prévision par menu
        q_prev = (
            select(
                LignePrevision.menu_id.label("menu_id"),
                func.coalesce(func.sum(LignePrevision.quantite_prevue), 0.0).label("qte_prevue"),
            )
            .select_from(LignePrevision)
            .join(ExecutionPrevision, ExecutionPrevision.id == LignePrevision.execution_prevision_id)
            .where(LignePrevision.date_prevue == date_cible)
            .group_by(LignePrevision.menu_id)
        )
        if magasin_id is not None:
            q_prev = q_prev.where(ExecutionPrevision.magasin_id == magasin_id)
        prev_rows = (await self._session.execute(q_prev)).all()
        prev_by_menu: dict[UUID, float] = {mid: float(q or 0.0) for mid, q in prev_rows}

        # Réel par menu (ventes)
        q_reel = (
            select(
                Vente.menu_id.label("menu_id"),
                func.coalesce(func.sum(Vente.quantite), 0.0).label("qte_reelle"),
            )
            .select_from(Vente)
            .where(Vente.menu_id.is_not(None), Vente.date_vente >= debut_dt, Vente.date_vente <= fin_dt)
            .group_by(Vente.menu_id)
        )
        if magasin_id is not None:
            q_reel = q_reel.where(Vente.magasin_id == magasin_id)
        reel_rows = (await self._session.execute(q_reel)).all()
        reel_by_menu: dict[UUID, float] = {mid: float(q or 0.0) for mid, q in reel_rows if mid is not None}

        # Union des menus concernés
        menu_ids = sorted(set(prev_by_menu.keys()) | set(reel_by_menu.keys()), key=lambda x: str(x))
        if not menu_ids:
            return []

        res_menus = await self._session.execute(select(Menu.id, Menu.nom, Menu.prix).where(Menu.id.in_(menu_ids)))
        menus = {mid: (str(nom), float(prix or 0.0)) for mid, nom, prix in res_menus.all()}

        lignes: list[LigneProduit] = []
        for mid in menu_ids:
            nom, prix = menus.get(mid, ("Menu", 0.0))
            q_prev = float(prev_by_menu.get(mid, 0.0))
            q_reel = float(reel_by_menu.get(mid, 0.0))
            lignes.append(
                LigneProduit(
                    menu_id=mid,
                    menu_nom=nom,
                    quantite_prevue=q_prev,
                    quantite_reelle=q_reel,
                    ca_prevu=q_prev * prix,
                    ca_reel=q_reel * prix,
                )
            )

        # Tri : plus gros impact CA d'abord
        lignes.sort(key=lambda l: abs(l.ca_reel - l.ca_prevu), reverse=True)
        return lignes

    async def _courbe_horaire(
        self,
        *,
        date_cible: date,
        magasin_id: UUID | None,
        ca_prevu: float,
        q_prevue: float,
    ) -> list[PointHoraire]:
        debut_dt = datetime.combine(date_cible, time.min).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(date_cible, time.max).replace(tzinfo=timezone.utc)

        # Réel horaire (quantités)
        q = (
            select(
                func.extract("hour", Vente.date_vente).label("h"),
                func.coalesce(func.sum(Vente.quantite), 0.0).label("qte"),
            )
            .select_from(Vente)
            .where(Vente.date_vente >= debut_dt, Vente.date_vente <= fin_dt)
            .group_by("h")
            .order_by("h")
        )
        if magasin_id is not None:
            q = q.where(Vente.magasin_id == magasin_id)

        rows = (await self._session.execute(q)).all()
        reel_par_heure: dict[int, float] = {int(h): float(q or 0.0) for h, q in rows if h is not None}

        total_reel = sum(reel_par_heure.values())
        # Distribution: si aucun réel -> uniforme
        poids: dict[int, float] = {}
        for h in range(24):
            if total_reel > 0:
                poids[h] = reel_par_heure.get(h, 0.0) / total_reel
            else:
                poids[h] = 1.0 / 24.0

        courbe: list[PointHoraire] = []

        # CA réel horaire: proxy en valorisant au prix menu moyen du jour (pas stocké par vente)
        # Pour le MVP, on dérive un prix moyen = ca_reel_total / qte_reelle_total si possible.
        # Ici on n'a pas ca_reel_total; on le reconstruira côté endpoint à partir table produits.
        # On laisse le CA horaire comme proxy (0 si pas de données), et on dérive le CA prévu via poids.
        # => le graphe principal est surtout la courbe quantités.

        for h in range(24):
            q_reel = float(reel_par_heure.get(h, 0.0))
            q_prev = float(q_prevue) * float(poids[h])
            courbe.append(
                PointHoraire(
                    heure=h,
                    quantite_prevue=q_prev,
                    quantite_reelle=q_reel,
                    ca_prevu=float(ca_prevu) * float(poids[h]),
                    ca_reel=0.0,
                )
            )

        return courbe

    async def _fiabilite_ca(self, *, date_cible: date, magasin_id: UUID | None, fenetre_jours: int) -> Fiabilite:
        if fenetre_jours <= 0:
            return Fiabilite(wape_ca_pct=None, mape_ca_pct=None, fiabilite_ca_pct=None)

        debut = date_cible - timedelta(days=fenetre_jours)
        fin = date_cible - timedelta(days=1)
        if fin < debut:
            return Fiabilite(wape_ca_pct=None, mape_ca_pct=None, fiabilite_ca_pct=None)

        # On calcule le CA réel et prévu par jour sur la fenêtre
        # Réel: ventes (prix menu)
        debut_dt = datetime.combine(debut, time.min).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(fin, time.max).replace(tzinfo=timezone.utc)

        # CA réel par jour
        q_reel = (
            select(
                func.date(Vente.date_vente).label("jour"),
                func.coalesce(func.sum(Vente.quantite * Menu.prix), 0.0).label("ca"),
            )
            .select_from(Vente)
            .join(Menu, Menu.id == Vente.menu_id)
            .where(Vente.date_vente >= debut_dt, Vente.date_vente <= fin_dt)
            .group_by("jour")
        )
        if magasin_id is not None:
            q_reel = q_reel.where(Vente.magasin_id == magasin_id)

        reel = {row[0]: float(row[1] or 0.0) for row in (await self._session.execute(q_reel)).all()}

        # CA prévu par jour
        q_prev = (
            select(
                LignePrevision.date_prevue.label("jour"),
                func.coalesce(func.sum(LignePrevision.quantite_prevue * Menu.prix), 0.0).label("ca"),
            )
            .select_from(LignePrevision)
            .join(Menu, Menu.id == LignePrevision.menu_id)
            .join(ExecutionPrevision, ExecutionPrevision.id == LignePrevision.execution_prevision_id)
            .where(LignePrevision.date_prevue >= debut, LignePrevision.date_prevue <= fin)
            .group_by("jour")
        )
        if magasin_id is not None:
            q_prev = q_prev.where(ExecutionPrevision.magasin_id == magasin_id)

        prev = {row[0]: float(row[1] or 0.0) for row in (await self._session.execute(q_prev)).all()}

        # Fenêtre complète jour par jour
        erreurs_abs = []
        erreurs_rel = []
        somme_reel = 0.0
        somme_abs = 0.0

        jour = debut
        while jour <= fin:
            r = float(reel.get(jour, 0.0))
            p = float(prev.get(jour, 0.0))
            err = abs(r - p)
            somme_abs += err
            somme_reel += r
            if r > 0:
                erreurs_rel.append(err / r)
            erreurs_abs.append(err)
            jour = jour + timedelta(days=1)

        if somme_reel <= 0:
            return Fiabilite(wape_ca_pct=None, mape_ca_pct=None, fiabilite_ca_pct=None)

        wape = (somme_abs / somme_reel) * 100.0
        mape = (sum(erreurs_rel) / len(erreurs_rel) * 100.0) if erreurs_rel else None
        fiab = max(0.0, 100.0 - wape)
        return Fiabilite(wape_ca_pct=wape, mape_ca_pct=mape, fiabilite_ca_pct=fiab)
