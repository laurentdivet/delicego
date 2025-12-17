from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
from app.domaine.modeles.referentiel import Fournisseur, Ingredient


@dataclass(frozen=True)
class LigneDashboardFournisseur:
    fournisseur_id: UUID
    fournisseur_nom: str
    total_commandes: int
    total_montant_commande: float
    total_montant_recu: float
    taux_reception: float
    derniere_commande_date: date | None


class DashboardFournisseursService:
    """Dashboard fournisseurs V1 (strict).

    Lecture seule.
    Agrégations simples par fournisseur.

    Définitions V1 :
    - total_commandes : COUNT(CommandeFournisseur)
    - total_montant_commande : SUM(ligne.quantite * ingredient.cout_unitaire)
    - total_montant_recu : SUM(ligne.quantite_recue * ingredient.cout_unitaire)
    - taux_reception : total_montant_recu / total_montant_commande (0 si dénominateur = 0)
    - derniere_commande_date : MAX(commande.date_commande)

    Filtres optionnels :
    - date_start / date_end inclusifs, appliqués sur CommandeFournisseur.date_commande.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lire(
        self,
        *,
        date_start: date | None = None,
        date_end: date | None = None,
    ) -> list[LigneDashboardFournisseur]:
        debut = self._borne_debut(date_start)
        fin = self._borne_fin(date_end)

        montant_commande = func.coalesce(func.sum(LigneCommandeFournisseur.quantite * Ingredient.cout_unitaire), 0.0)
        montant_recu = func.coalesce(func.sum(LigneCommandeFournisseur.quantite_recue * Ingredient.cout_unitaire), 0.0)
        total_commandes = func.count(func.distinct(CommandeFournisseur.id))
        derniere_date = func.max(func.date(CommandeFournisseur.date_commande))

        conditions_join_cmd = [CommandeFournisseur.fournisseur_id == Fournisseur.id]
        if debut is not None:
            conditions_join_cmd.append(CommandeFournisseur.date_commande >= debut)
        if fin is not None:
            conditions_join_cmd.append(CommandeFournisseur.date_commande <= fin)

        stmt = (
            select(
                Fournisseur.id,
                Fournisseur.nom,
                total_commandes.label("total_commandes"),
                montant_commande.label("total_montant_commande"),
                montant_recu.label("total_montant_recu"),
                derniere_date.label("derniere_commande_date"),
            )
            .select_from(Fournisseur)
            .join(CommandeFournisseur, and_(*conditions_join_cmd), isouter=True)
            .join(
                LigneCommandeFournisseur,
                LigneCommandeFournisseur.commande_fournisseur_id == CommandeFournisseur.id,
                isouter=True,
            )
            .join(Ingredient, Ingredient.id == LigneCommandeFournisseur.ingredient_id, isouter=True)
            .group_by(Fournisseur.id, Fournisseur.nom)
            .order_by(Fournisseur.nom.asc())
        )

        res = await self._session.execute(stmt)

        lignes: list[LigneDashboardFournisseur] = []
        for fournisseur_id, fournisseur_nom, nb, m_cmd, m_rec, last_dt in res.all():
            m_cmd_f = float(m_cmd or 0.0)
            m_rec_f = float(m_rec or 0.0)
            taux = float(m_rec_f / m_cmd_f) if m_cmd_f > 0 else 0.0

            lignes.append(
                LigneDashboardFournisseur(
                    fournisseur_id=fournisseur_id,
                    fournisseur_nom=str(fournisseur_nom),
                    total_commandes=int(nb or 0),
                    total_montant_commande=m_cmd_f,
                    total_montant_recu=m_rec_f,
                    taux_reception=taux,
                    derniere_commande_date=last_dt,
                )
            )

        return lignes

    @staticmethod
    def _borne_debut(d: date | None) -> datetime | None:
        if d is None:
            return None
        return datetime.combine(d, time.min, tzinfo=timezone.utc)

    @staticmethod
    def _borne_fin(d: date | None) -> datetime | None:
        if d is None:
            return None
        return datetime.combine(d, time.max, tzinfo=timezone.utc)
