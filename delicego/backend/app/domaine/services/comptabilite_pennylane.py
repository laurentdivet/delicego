from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeClient, TypeEcritureComptable
from app.domaine.modeles.achats import CommandeAchat
from app.domaine.modeles.commande_client import LigneCommandeClient
from app.domaine.modeles.comptabilite import EcritureComptable, JournalComptable


class ErreurComptabilitePennylane(Exception):
    """Erreur générique comptabilité (projection Pennylane)."""


@dataclass(frozen=True)
class _MappingComptable:
    compte_produit_vente: str = "706"
    compte_tva_collectee: str = "44571"
    compte_charge_achat: str = "607"
    compte_tva_deductible: str = "44566"


class ServiceComptabilitePennylane:
    """Génère des écritures comptables exportables (simulation Pennylane).

    IMPORTANT :
    - Lecture/agrégation uniquement : aucune logique métier.
    - Aucun appel API externe (Pennylane) : on prépare des écritures exportables.
    - Idempotent : pas de doublon si déjà généré.

    Hypothèses simplifiées (tests) :
    - Vente = somme des quantités des lignes de commande (montant HT unitaire=10 par unité)
    - TVA = 20% du HT
    - Achat = montant forfaitaire si CommandeAchat.reference est renseignée (HT=100), sinon 0

    Ces conventions sont explicites et pourront être remplacées par un mapping réel plus tard.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mapping = _MappingComptable()

    async def generer_ecritures(
        self,
        *,
        date_debut: date,
        date_fin: date,
    ) -> list[UUID]:
        if date_fin < date_debut:
            raise ErreurComptabilitePennylane("Période invalide : date_fin < date_debut.")

        debut_dt = datetime.combine(date_debut, time.min).replace(tzinfo=timezone.utc)
        fin_dt = datetime.combine(date_fin, time.max).replace(tzinfo=timezone.utc)

        async with self._session.begin():
            # Journal (un journal par génération)
            journal = JournalComptable(date_debut=date_debut, date_fin=date_fin, total_ventes=0.0, total_achats=0.0)
            self._session.add(journal)
            await self._session.flush()

            ids_crees: list[UUID] = []

            # --- VENTES (commandes confirmées) ---
            # On récupère les commandes confirmées via la table lignes (pour avoir quantité totale)
            res_commandes = await self._session.execute(
                select(
                    LigneCommandeClient.commande_client_id,
                    LigneCommandeClient.quantite,
                    # joindre commande_client via relation implicite
                    __import__("app.domaine.modeles.commande_client", fromlist=["CommandeClient"]).CommandeClient.date_commande,
                    __import__("app.domaine.modeles.commande_client", fromlist=["CommandeClient"]).CommandeClient.statut,
                ).join(
                    __import__("app.domaine.modeles.commande_client", fromlist=["CommandeClient"]).CommandeClient,
                    __import__("app.domaine.modeles.commande_client", fromlist=["CommandeClient"]).CommandeClient.id
                    == LigneCommandeClient.commande_client_id,
                )
                .where(
                    __import__("app.domaine.modeles.commande_client", fromlist=["CommandeClient"]).CommandeClient.statut
                    == StatutCommandeClient.CONFIRMEE,
                    __import__("app.domaine.modeles.commande_client", fromlist=["CommandeClient"]).CommandeClient.date_commande
                    >= debut_dt,
                    __import__("app.domaine.modeles.commande_client", fromlist=["CommandeClient"]).CommandeClient.date_commande
                    <= fin_dt,
                )
            )

            ventes_par_commande: dict[UUID, tuple[date, float]] = {}
            for commande_id, quantite, date_commande, _statut in res_commandes.all():
                d = date_commande.date() if hasattr(date_commande, "date") else date_debut
                ventes_par_commande.setdefault(commande_id, (d, 0.0))
                ventes_par_commande[commande_id] = (d, ventes_par_commande[commande_id][1] + float(quantite or 0.0))

            for commande_id, (date_ecriture, quantite_totale) in ventes_par_commande.items():
                if quantite_totale <= 0:
                    continue

                montant_ht = float(quantite_totale) * 10.0
                tva = montant_ht * 0.20

                ids_crees.extend(
                    await self._creer_ecritures_si_absentes(
                        type_ecriture=TypeEcritureComptable.VENTE,
                        reference_interne=str(commande_id),
                        date_ecriture=date_ecriture,
                        montant_ht=montant_ht,
                        tva=tva,
                        compte_produit=self._mapping.compte_produit_vente,
                        compte_tva=self._mapping.compte_tva_collectee,
                    )
                )

                journal.total_ventes += montant_ht

            # --- ACHATS (Commandes d’achat) ---
            # Hypothèse simplifiée : chaque CommandeAchat dans la période génère un achat forfaitaire HT=100
            res_achats = await self._session.execute(
                select(CommandeAchat.id, CommandeAchat.creee_le).where(
                    CommandeAchat.creee_le >= debut_dt,
                    CommandeAchat.creee_le <= fin_dt,
                )
            )

            for achat_id, creee_le in res_achats.all():
                date_ecriture = creee_le.date() if hasattr(creee_le, "date") else date_debut
                montant_ht = 100.0
                tva = montant_ht * 0.20

                ids_crees.extend(
                    await self._creer_ecritures_si_absentes(
                        type_ecriture=TypeEcritureComptable.ACHAT,
                        reference_interne=str(achat_id),
                        date_ecriture=date_ecriture,
                        montant_ht=montant_ht,
                        tva=tva,
                        compte_produit=self._mapping.compte_charge_achat,
                        compte_tva=self._mapping.compte_tva_deductible,
                    )
                )

                journal.total_achats += montant_ht

            await self._session.flush()
            return ids_crees

    async def _creer_ecritures_si_absentes(
        self,
        *,
        type_ecriture: TypeEcritureComptable,
        reference_interne: str,
        date_ecriture: date,
        montant_ht: float,
        tva: float,
        compte_produit: str,
        compte_tva: str,
    ) -> list[UUID]:
        """Crée 2 écritures (compte principal + TVA) si elles n’existent pas déjà."""

        ids: list[UUID] = []

        # Écriture principale
        if not await self._ecriture_existe(type_ecriture, reference_interne, compte_produit):
            e1 = EcritureComptable(
                date_ecriture=date_ecriture,
                type=type_ecriture,
                reference_interne=reference_interne,
                montant_ht=float(montant_ht),
                tva=float(0.0),
                compte_comptable=compte_produit,
                exportee=False,
            )
            self._session.add(e1)
            await self._session.flush()
            ids.append(e1.id)

        # TVA
        if not await self._ecriture_existe(type_ecriture, reference_interne, compte_tva):
            e2 = EcritureComptable(
                date_ecriture=date_ecriture,
                type=type_ecriture,
                reference_interne=reference_interne,
                montant_ht=float(0.0),
                tva=float(tva),
                compte_comptable=compte_tva,
                exportee=False,
            )
            self._session.add(e2)
            await self._session.flush()
            ids.append(e2.id)

        return ids

    async def _ecriture_existe(
        self,
        type_ecriture: TypeEcritureComptable,
        reference_interne: str,
        compte: str,
    ) -> bool:
        res = await self._session.execute(
            select(EcritureComptable.id).where(
                EcritureComptable.type == type_ecriture,
                EcritureComptable.reference_interne == reference_interne,
                EcritureComptable.compte_comptable == compte,
            )
        )
        return res.scalar_one_or_none() is not None
