from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from uuid import UUID

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
from app.domaine.modeles.referentiel import Fournisseur, Ingredient


class ErreurBonCommandeFournisseur(Exception):
    """Erreur générique de génération du bon de commande fournisseur (PDF)."""


class BonCommandeIntrouvable(ErreurBonCommandeFournisseur):
    """Commande fournisseur introuvable."""


@dataclass(frozen=True)
class LigneBonCommande:
    ingredient: str
    quantite: float
    unite: str
    prix_unitaire: float

    @property
    def total(self) -> float:
        return float(self.quantite) * float(self.prix_unitaire)


@dataclass(frozen=True)
class DonneesBonCommande:
    numero_commande: str
    fournisseur: str
    date_commande: date
    lignes: list[LigneBonCommande]

    @property
    def total_ht(self) -> float:
        return float(sum(l.total for l in self.lignes))

    @property
    def tva(self) -> float:
        return self.total_ht * 0.20

    @property
    def total_ttc(self) -> float:
        return self.total_ht + self.tva


class ServiceBonCommandeFournisseur:
    """Génère un PDF "bon de commande" à partir d’une `CommandeFournisseur`.

    Contraintes :
    - Pas d’accès disque obligatoire : on retourne des bytes.
    - Service pur/testable.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def generer_pdf(self, commande_id: UUID) -> bytes:
        """Retourne le PDF du bon de commande en bytes (aucun accès disque)."""

        donnees = await self._charger_donnees(commande_id=commande_id)
        return self._render_pdf(donnees)

    async def _charger_donnees(self, *, commande_id: UUID) -> DonneesBonCommande:
        res_cmd = await self._session.execute(select(CommandeFournisseur).where(CommandeFournisseur.id == commande_id))
        commande = res_cmd.scalar_one_or_none()
        if commande is None:
            raise BonCommandeIntrouvable("CommandeFournisseur introuvable.")

        res_four = await self._session.execute(select(Fournisseur.nom).where(Fournisseur.id == commande.fournisseur_id))
        nom_fournisseur = res_four.scalar_one_or_none() or "(inconnu)"

        res_lignes = await self._session.execute(
            select(
                LigneCommandeFournisseur.ingredient_id,
                LigneCommandeFournisseur.quantite,
                LigneCommandeFournisseur.unite,
            ).where(LigneCommandeFournisseur.commande_fournisseur_id == commande.id)
        )

        lignes: list[LigneBonCommande] = []
        for ingredient_id, quantite, unite in res_lignes.all():
            res_ing = await self._session.execute(
                select(Ingredient.nom, Ingredient.cout_unitaire).where(Ingredient.id == ingredient_id)
            )
            nom_ing, prix_unit = res_ing.one()
            lignes.append(
                LigneBonCommande(
                    ingredient=str(nom_ing),
                    quantite=float(quantite or 0.0),
                    unite=str(unite),
                    prix_unitaire=float(prix_unit or 0.0),
                )
            )

        return DonneesBonCommande(
            numero_commande=str(commande.id),
            fournisseur=str(nom_fournisseur),
            date_commande=commande.date_commande.date(),
            lignes=lignes,
        )

    @staticmethod
    def _render_pdf(donnees: DonneesBonCommande) -> bytes:
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        largeur, hauteur = A4

        y = hauteur - 20 * mm
        c.setFont("Helvetica-Bold", 14)
        c.drawString(20 * mm, y, "Bon de commande fournisseur")

        y -= 10 * mm
        c.setFont("Helvetica", 10)
        c.drawString(20 * mm, y, f"Fournisseur : {donnees.fournisseur}")
        y -= 5 * mm
        c.drawString(20 * mm, y, f"Date : {donnees.date_commande.isoformat()}")
        y -= 5 * mm
        c.drawString(20 * mm, y, f"Numéro : {donnees.numero_commande}")

        y -= 10 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y, "Ingrédient")
        c.drawString(110 * mm, y, "Qté")
        c.drawString(130 * mm, y, "Unité")
        c.drawString(150 * mm, y, "PU")
        c.drawString(175 * mm, y, "Total")

        c.setFont("Helvetica", 10)
        y -= 6 * mm

        for ligne in donnees.lignes:
            if y < 25 * mm:
                c.showPage()
                y = hauteur - 20 * mm
                c.setFont("Helvetica", 10)

            c.drawString(20 * mm, y, ligne.ingredient)
            c.drawRightString(125 * mm, y, f"{ligne.quantite:.2f}")
            c.drawString(130 * mm, y, ligne.unite)
            c.drawRightString(170 * mm, y, f"{ligne.prix_unitaire:.2f}")
            c.drawRightString(200 * mm, y, f"{ligne.total:.2f}")
            y -= 5 * mm

        y -= 8 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(170 * mm, y, "Total HT")
        c.drawRightString(200 * mm, y, f"{donnees.total_ht:.2f}")
        y -= 5 * mm
        c.drawRightString(170 * mm, y, "TVA (20%)")
        c.drawRightString(200 * mm, y, f"{donnees.tva:.2f}")
        y -= 5 * mm
        c.drawRightString(170 * mm, y, "Total TTC")
        c.drawRightString(200 * mm, y, f"{donnees.total_ttc:.2f}")

        c.showPage()
        c.save()
        return buffer.getvalue()
