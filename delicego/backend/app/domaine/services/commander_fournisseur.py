from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.enums.types import StatutCommandeFournisseur, TypeEcritureComptable, TypeMouvementStock
from app.domaine.modeles.achats import CommandeFournisseur, LigneCommandeFournisseur
from app.domaine.modeles.comptabilite import EcritureComptable
from app.domaine.modeles.referentiel import Fournisseur, Ingredient, Magasin
from app.domaine.modeles.stock_tracabilite import Lot, MouvementStock


class ErreurCommandeFournisseur(Exception):
    """Erreur générique de commande fournisseur."""


class DonneesInvalidesCommandeFournisseur(ErreurCommandeFournisseur):
    """La commande ne peut pas être créée/modifiée (ids, quantités…)."""


class TransitionStatutInterditeCommandeFournisseur(ErreurCommandeFournisseur):
    """Transition de statut invalide (ex: envoyer une commande déjà envoyée)."""


class CommandeFournisseurIntrouvable(ErreurCommandeFournisseur):
    """Commande introuvable."""


class ServiceCommandeFournisseur:
    """Service métier : commandes fournisseurs + réception.

    Règles d’or :
    - AUCUN impact stock avant `receptionner_commande`.
    - Réception possible en plusieurs fois (partielle), uniquement sur les quantités reçues.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def creer_commande(
        self,
        *,
        fournisseur_id: UUID,
        date_commande: datetime | None = None,
        commentaire: str | None = None,
    ) -> UUID:
        if date_commande is None:
            date_commande = datetime.now(timezone.utc)

        # IMPORTANT : ne pas exécuter de requête AVANT `begin()` (autobegin SQLAlchemy).
        async with self._session.begin():
            await self._verifier_fournisseur_existe(fournisseur_id)

            commande = CommandeFournisseur(
                fournisseur_id=fournisseur_id,
                date_commande=date_commande,
                statut=StatutCommandeFournisseur.BROUILLON,
                commentaire=commentaire,
            )
            self._session.add(commande)
            await self._session.flush()
            return commande.id

    async def ajouter_ligne(
        self,
        *,
        commande_fournisseur_id: UUID,
        ingredient_id: UUID,
        quantite: float,
        unite: str,
    ) -> UUID:
        if ingredient_id is None:
            raise DonneesInvalidesCommandeFournisseur("ingredient_id est obligatoire.")
        if quantite is None or float(quantite) <= 0:
            raise DonneesInvalidesCommandeFournisseur("La quantité doit être > 0.")
        if unite is None or not str(unite).strip():
            raise DonneesInvalidesCommandeFournisseur("L’unité est obligatoire.")

        async with self._session.begin():
            commande = await self._charger_commande(commande_fournisseur_id)
            if commande.statut != StatutCommandeFournisseur.BROUILLON:
                raise TransitionStatutInterditeCommandeFournisseur(
                    "On ne peut ajouter des lignes que sur une commande en BROUILLON."
                )

            # IMPORTANT : on est déjà dans `begin()`
            await self._verifier_ingredient_existe(ingredient_id)

            ligne = LigneCommandeFournisseur(
                commande_fournisseur_id=commande.id,
                ingredient_id=ingredient_id,
                quantite=float(quantite),
                unite=str(unite),
            )
            self._session.add(ligne)
            await self._session.flush()
            return ligne.id

    async def envoyer_commande(self, *, commande_fournisseur_id: UUID) -> None:
        async with self._session.begin():
            commande = await self._charger_commande(commande_fournisseur_id)
            if commande.statut != StatutCommandeFournisseur.BROUILLON:
                raise TransitionStatutInterditeCommandeFournisseur("La commande n’est pas en BROUILLON.")

            # Exiger au moins une ligne avant envoi
            res = await self._session.execute(
                select(LigneCommandeFournisseur.id).where(
                    LigneCommandeFournisseur.commande_fournisseur_id == commande.id
                )
            )
            if res.scalar_one_or_none() is None:
                raise DonneesInvalidesCommandeFournisseur("Impossible d’envoyer une commande sans lignes.")

            commande.statut = StatutCommandeFournisseur.ENVOYEE
            await self._session.flush()

    async def receptionner_commande(
        self,
        *,
        commande_fournisseur_id: UUID,
        magasin_id: UUID,
        # si None : on réceptionne exactement le reliquat (quantite - quantite_recue)
        lignes_reception: list[tuple[UUID, float, str]] | None = None,
        reference_externe: str | None = None,
        commentaire: str | None = None,
    ) -> None:
        """Réceptionne une commande fournisseur : stock + lots + écritures.

        lignes_reception : liste de tuples (ingredient_id, quantite, unite)

        Transaction atomique.
        """

        if magasin_id is None:
            raise DonneesInvalidesCommandeFournisseur("magasin_id est obligatoire.")

        moteur = self._session.bind
        if moteur is None:
            raise ErreurCommandeFournisseur("Session SQLAlchemy non liée à un moteur.")

        async with moteur.connect() as connexion:  # type: ignore[union-attr]
            async with connexion.begin():
                # Session dédiée à l’écriture (évite les transactions imbriquées si un autre service est appelé)
                session = AsyncSession(bind=connexion, expire_on_commit=False)
                try:
                    # validations de base
                    await self._verifier_magasin_existe(magasin_id, session=session)

                    res = await session.execute(
                        select(CommandeFournisseur).where(CommandeFournisseur.id == commande_fournisseur_id)
                    )
                    commande = res.scalar_one_or_none()
                    if commande is None:
                        raise CommandeFournisseurIntrouvable("CommandeFournisseur introuvable.")

                    if commande.statut not in (StatutCommandeFournisseur.ENVOYEE, StatutCommandeFournisseur.PARTIELLE):
                        raise TransitionStatutInterditeCommandeFournisseur(
                            "On ne peut réceptionner que des commandes ENVOYEE ou PARTIELLE."
                        )

                    # Construire les lignes de réception
                    if lignes_reception is None:
                        # Par défaut on réceptionne le reliquat par ligne
                        res_lignes = await session.execute(
                            select(
                                LigneCommandeFournisseur.ingredient_id,
                                LigneCommandeFournisseur.quantite,
                                LigneCommandeFournisseur.quantite_recue,
                                LigneCommandeFournisseur.unite,
                            ).where(LigneCommandeFournisseur.commande_fournisseur_id == commande.id)
                        )
                        lignes_reception = []
                        for ingredient_id, qte_cmd, qte_recue, unite in res_lignes.all():
                            reliquat = float(qte_cmd) - float(qte_recue or 0.0)
                            if reliquat > 0:
                                lignes_reception.append((ingredient_id, float(reliquat), str(unite)))

                    if not lignes_reception:
                        raise DonneesInvalidesCommandeFournisseur("Réception vide : aucune ligne.")

                    # Index des lignes commande (pour maj quantite_recue et contrôles)
                    res_lignes_cmd = await session.execute(
                        select(
                            LigneCommandeFournisseur.ingredient_id,
                            LigneCommandeFournisseur.quantite,
                            LigneCommandeFournisseur.quantite_recue,
                            LigneCommandeFournisseur.unite,
                        ).where(LigneCommandeFournisseur.commande_fournisseur_id == commande.id)
                    )
                    lignes_cmd = {
                        ingredient_id: (float(qte_cmd), float(qte_recue or 0.0), str(unite_cmd))
                        for ingredient_id, qte_cmd, qte_recue, unite_cmd in res_lignes_cmd.all()
                    }

                    for ingredient_id, quantite, unite in lignes_reception:
                        if ingredient_id is None:
                            raise DonneesInvalidesCommandeFournisseur("ingredient_id manquant dans une ligne.")
                        if quantite is None or float(quantite) <= 0:
                            raise DonneesInvalidesCommandeFournisseur("Quantité de réception invalide.")
                        if unite is None or not str(unite).strip():
                            raise DonneesInvalidesCommandeFournisseur("Unité de réception invalide.")

                        if ingredient_id not in lignes_cmd:
                            raise DonneesInvalidesCommandeFournisseur(
                                "Ingrédient réceptionné non présent dans la commande."
                            )

                        qte_cmd, qte_recue, unite_cmd = lignes_cmd[ingredient_id]
                        if str(unite) != unite_cmd:
                            raise DonneesInvalidesCommandeFournisseur("Unité de réception différente de la commande.")

                        # interdire de réceptionner plus que le reliquat
                        reliquat = float(qte_cmd) - float(qte_recue)
                        if float(quantite) > reliquat + 1e-9:
                            raise DonneesInvalidesCommandeFournisseur("Quantité de réception > reliquat.")

                    # 1) Créer lots + mouvements stock + maj quantite_recue
                    for ingredient_id, quantite, unite in lignes_reception:
                        # Vérifier ingredient existe
                        await self._verifier_ingredient_existe(ingredient_id, session=session)

                        lot = Lot(
                            magasin_id=magasin_id,
                            ingredient_id=ingredient_id,
                            fournisseur_id=commande.fournisseur_id,
                            code_lot=reference_externe,
                            date_dlc=None,
                            unite=str(unite),
                        )
                        session.add(lot)
                        await session.flush()  # obtenir lot.id

                        mouvement = MouvementStock(
                            type_mouvement=TypeMouvementStock.RECEPTION,
                            magasin_id=magasin_id,
                            ingredient_id=ingredient_id,
                            lot_id=lot.id,
                            quantite=float(quantite),
                            unite=str(unite),
                            reference_externe=reference_externe or str(commande.id),
                            commentaire=commentaire,
                        )
                        session.add(mouvement)

                        # Maj cumulée sur la ligne de commande
                        res_ligne = await session.execute(
                            select(LigneCommandeFournisseur).where(
                                LigneCommandeFournisseur.commande_fournisseur_id == commande.id,
                                LigneCommandeFournisseur.ingredient_id == ingredient_id,
                            )
                        )
                        ligne = res_ligne.scalar_one()
                        ligne.quantite_recue = float(ligne.quantite_recue or 0.0) + float(quantite)

                    # 2) Écritures comptables (607 / 44566) — proportionnelles à la quantité réellement reçue.
                    # Hypothèse cohérente avec le projet : prix d’achat = coût unitaire ingrédient * quantité.
                    # TVA forfaitaire à 20%.
                    montant_ht = await self._calculer_montant_ht(session=session, lignes=lignes_reception)
                    tva = float(montant_ht) * 0.20

                    date_ecriture = (
                        commande.date_commande.date()
                        if hasattr(commande.date_commande, "date")
                        else datetime.now(timezone.utc).date()
                    )

                    # Écritures comptables : une paire (607/44566) par réception.
                    # On conserve l’unicité (type, reference_interne, compte) du modèle en
                    # différenciant `reference_interne` par un suffixe de réception.
                    res_nb = await session.execute(
                        select(EcritureComptable.reference_interne).where(
                            EcritureComptable.type == TypeEcritureComptable.ACHAT,
                            EcritureComptable.reference_interne.like(f"{commande.id}:%"),
                        )
                    )
                    numero_reception = len({str(r).split(":")[-1] for r in res_nb.scalars().all() if r is not None}) + 1
                    reference_interne = f"{commande.id}:{numero_reception}"

                    # 607 : charge achat
                    session.add(
                        EcritureComptable(
                            date_ecriture=date_ecriture,
                            type=TypeEcritureComptable.ACHAT,
                            reference_interne=reference_interne,
                            montant_ht=float(montant_ht),
                            tva=float(0.0),
                            compte_comptable="607",
                            exportee=False,
                        )
                    )
                    # 44566 : TVA déductible
                    session.add(
                        EcritureComptable(
                            date_ecriture=date_ecriture,
                            type=TypeEcritureComptable.ACHAT,
                            reference_interne=reference_interne,
                            montant_ht=float(0.0),
                            tva=float(tva),
                            compte_comptable="44566",
                            exportee=False,
                        )
                    )

                    # 3) statut : PARTIELLE si au moins une ligne non soldée, sinon RECEPTIONNEE
                    res_soldes = await session.execute(
                        select(
                            LigneCommandeFournisseur.quantite,
                            LigneCommandeFournisseur.quantite_recue,
                        ).where(LigneCommandeFournisseur.commande_fournisseur_id == commande.id)
                    )
                    toutes_soldees = all(float(qte_recue or 0.0) >= float(qte_cmd) for qte_cmd, qte_recue in res_soldes.all())
                    commande.statut = (
                        StatutCommandeFournisseur.RECEPTIONNEE
                        if toutes_soldees
                        else StatutCommandeFournisseur.PARTIELLE
                    )

                    await session.flush()
                finally:
                    await session.close()

    async def _charger_commande(self, commande_fournisseur_id: UUID) -> CommandeFournisseur:
        res = await self._session.execute(
            select(CommandeFournisseur).where(CommandeFournisseur.id == commande_fournisseur_id)
        )
        commande = res.scalar_one_or_none()
        if commande is None:
            raise CommandeFournisseurIntrouvable("CommandeFournisseur introuvable.")
        return commande

    async def _verifier_fournisseur_existe(self, fournisseur_id: UUID) -> None:
        res = await self._session.execute(select(Fournisseur.id).where(Fournisseur.id == fournisseur_id))
        if res.scalar_one_or_none() is None:
            raise DonneesInvalidesCommandeFournisseur("Fournisseur introuvable.")

    async def _verifier_magasin_existe(self, magasin_id: UUID, *, session: AsyncSession) -> None:
        res = await session.execute(select(Magasin.id).where(Magasin.id == magasin_id))
        if res.scalar_one_or_none() is None:
            raise DonneesInvalidesCommandeFournisseur("Magasin introuvable.")

    async def _verifier_ingredient_existe(self, ingredient_id: UUID, *, session: AsyncSession | None = None) -> None:
        sess = session or self._session
        res = await sess.execute(select(Ingredient.id).where(Ingredient.id == ingredient_id))
        if res.scalar_one_or_none() is None:
            raise DonneesInvalidesCommandeFournisseur("Ingrédient introuvable.")

    async def _calculer_montant_ht(
        self,
        *,
        session: AsyncSession,
        lignes: list[tuple[UUID, float, str]],
    ) -> float:
        """Montant HT calculé depuis `Ingredient.cout_unitaire`.

        NOTE : on suppose que l’unité est cohérente avec l’unité de mesure du coût.
        """

        total = 0.0
        for ingredient_id, quantite, _unite in lignes:
            res = await session.execute(select(Ingredient.cout_unitaire).where(Ingredient.id == ingredient_id))
            cout_unitaire = float(res.scalar_one() or 0.0)
            total += cout_unitaire * float(quantite)
        return float(total)
