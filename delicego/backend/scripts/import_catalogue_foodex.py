from __future__ import annotations

"""Import catalogue fournisseur Foodex (PDF).

Source de vérité (métier): le PDF Foodex.

Objectifs:
- Créer/mettre à jour les `Produit` (dédoublonnage par libellé normalisé)
- Créer/mettre à jour les `ProduitFournisseur` (idempotent, clé: (fournisseur_id, reference_fournisseur))

IMPORTANT:
- Ne crée PAS d'ingredients/recettes/ventes.

Exécution (depuis backend/):

    python -m scripts.import_catalogue_foodex --pdf ../"FOODEX Tarif nov 2025.pdf" --dry-run
    python -m scripts.import_catalogue_foodex --pdf ../"FOODEX Tarif nov 2025.pdf"

"""

import argparse
import asyncio
import os
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.catalogue import Produit, ProduitFournisseur
from app.domaine.modeles.referentiel import Fournisseur


@dataclass(frozen=True)
class FoodexRow:
    stockage: str | None
    code: str
    ancien_code: str | None
    libelle: str
    marque: str | None
    unite_vente: str | None
    contenance: str | None
    prix_ht: float | None


def _normaliser_libelle(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_euro_float(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    # exemples: "29,60 €" / "3,90 €" / "170,80 €"
    s = s.replace("€", "").strip()
    s = s.replace("\xa0", " ").strip()
    s = s.replace(" ", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_pdf_lines(pdf_text: str) -> list[FoodexRow]:
    """Parse très pragmatique du texte extrait du PDF.

    Le PDF fourni est déjà un dump texte; on se base sur un format "ligne".
    Exemple:
      Sec11 203801 RIZ ... SAC 20KG 29,60 €

    Contraintes:
    - Référence = le premier code numérique après la catégorie (Sec11)
    - Ancien code = parfois présent (deuxième code numérique)
    - Prix HT = dernier token type "xx,xx €" (optionnel)
    - Unite vente + contenance = tokens typiques (SAC, CT, PCE, BIDON, BOUTEIL, CART, etc.)
    """

    rows: list[FoodexRow] = []
    for raw in pdf_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Stockage") or line.startswith("Pages"):
            continue

        m = re.match(r"^(?P<stockage>[A-Za-zéÉ]+\d+)\s+(?P<rest>.+)$", line)
        if not m:
            continue

        stockage = m.group("stockage")
        rest = m.group("rest")

        # extrait prix (optionnel)
        prix = None
        prix_m = re.search(r"(\d+[\.,]\d{2})\s*€\s*$", rest)
        if prix_m:
            prix = _parse_euro_float(prix_m.group(0))
            rest = rest[: prix_m.start()].rstrip()

        # split tokens
        tokens = rest.split()
        if len(tokens) < 2:
            continue

        # 1er token après stockage = code
        code = tokens[0]
        if not re.match(r"^\d{5,}$", code):
            continue

        # parfois un 2e code numérique suit
        ancien_code = None
        idx = 1
        if idx < len(tokens) and re.match(r"^\d{5,}$", tokens[idx]):
            ancien_code = tokens[idx]
            idx += 1

        # heuristique: les 2 derniers tokens sont souvent (unite_vente, contenance)
        # mais parfois: "CT1KG x 10" => on garde contenance brute.
        unite_vente = None
        contenance = None

        # tente de repérer une unité type SAC/CT/PCE/BIDON/BOUTEIL/CART/etc.
        known_units = {"SAC", "CT", "PCE", "BIDON", "BOUTEIL", "CART", "PAQUET", "PCS", "BOITE", "POT", "SEAU", "LOT"}
        # repère premier token de known_units en fin de ligne
        for j in range(len(tokens) - 1, idx - 1, -1):
            if tokens[j].upper() in known_units:
                unite_vente = tokens[j].upper()
                # contenance = tokens après unite_vente
                contenance = " ".join(tokens[j + 1 :]) if j + 1 < len(tokens) else None
                # libellé = tokens entre idx et j
                libelle = " ".join(tokens[idx:j]).strip()
                break
        else:
            # fallback: tout le reste
            libelle = " ".join(tokens[idx:]).strip()

        if not libelle:
            continue

        rows.append(
            FoodexRow(
                stockage=stockage,
                code=code,
                ancien_code=ancien_code,
                libelle=_normaliser_libelle(libelle),
                marque=None,
                unite_vente=unite_vente,
                contenance=contenance,
                prix_ht=prix,
            )
        )

    return rows


async def importer(*, pdf_path: str, dry_run: bool, fournisseur_nom: str = "Foodex") -> None:
    url_db = os.getenv("DATABASE_URL") or parametres_application.url_base_donnees
    engine = create_async_engine(url_db, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    with open(pdf_path, "rb") as f:
        # le read_file de Cline montre que c'est exploitable en texte brut; ici on tente utf-8.
        # Si le PDF est un vrai binaire, il faudra passer par un extracteur (à ajouter plus tard).
        try:
            text = f.read().decode("utf-8")
        except UnicodeDecodeError:
            raise RuntimeError(
                "Le fichier PDF ne semble pas être du texte brut. "
                "Merci de fournir une version exportée en texte/CSV, ou on ajoutera une extraction PDF (pdfplumber)."
            )

    rows = _parse_pdf_lines(text)
    if not rows:
        raise RuntimeError("Aucune ligne produit parsée depuis le PDF (format inattendu).")

    async with session_maker() as session:
        # fournisseur Foodex
        resf = await session.execute(select(Fournisseur).where(Fournisseur.nom == fournisseur_nom))
        fournisseur = resf.scalar_one_or_none()
        if fournisseur is None:
            fournisseur = Fournisseur(nom=fournisseur_nom, actif=True)
            session.add(fournisseur)
            await session.flush()

        created_produits = 0
        created_pf = 0
        updated_pf = 0

        for r in rows:
            # Produit: dédoublonnage par libellé
            res_p = await session.execute(select(Produit).where(Produit.libelle == r.libelle))
            produit = res_p.scalar_one_or_none()
            if produit is None:
                produit = Produit(libelle=r.libelle, categorie=r.stockage, actif=True)
                session.add(produit)
                await session.flush()
                created_produits += 1
            else:
                # on garde la catégorie si absente
                if produit.categorie is None and r.stockage:
                    produit.categorie = r.stockage

            # ProduitFournisseur: clé idempotente (fournisseur_id, reference_fournisseur)
            res_pf = await session.execute(
                select(ProduitFournisseur).where(
                    ProduitFournisseur.fournisseur_id == fournisseur.id,
                    ProduitFournisseur.reference_fournisseur == r.code,
                )
            )
            pf = res_pf.scalar_one_or_none()

            unite = (r.unite_vente or "PCE").lower()
            quantite = 1.0
            # contenance typique: "20KG" / "1.8L" / "150mL X 6" / "10mL x 800"
            if r.contenance:
                m_qty = re.match(r"^(\d+(?:[\.,]\d+)?)\s*(KG|G|L|ML)\b", r.contenance.replace(",", "."), re.IGNORECASE)
                if m_qty:
                    quantite = float(m_qty.group(1))
                    # si contenance en g/ml, la quantite est dans cette unité.
                    # on conserve l'unité d'achat issue de unite_vente, car c'est le conditionnement.

            if pf is None:
                pf = ProduitFournisseur(
                    produit_id=produit.id,
                    fournisseur_id=fournisseur.id,
                    reference_fournisseur=r.code,
                    libelle_fournisseur=r.libelle,
                    unite_achat=unite,
                    quantite_par_unite=quantite,
                    prix_achat_ht=r.prix_ht,
                    tva=None,
                    actif=True,
                )
                session.add(pf)
                created_pf += 1
            else:
                pf.produit_id = produit.id
                pf.libelle_fournisseur = r.libelle
                pf.unite_achat = unite
                pf.quantite_par_unite = quantite
                pf.prix_achat_ht = r.prix_ht
                pf.actif = True
                updated_pf += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

        print(
            f"[foodex] lignes={len(rows)} produits_crees={created_produits} pf_crees={created_pf} pf_maj={updated_pf} dry_run={dry_run}"
        )

    await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import catalogue Foodex")
    p.add_argument("--pdf", required=True, help="Chemin vers le PDF (ou texte brut) Foodex")
    p.add_argument("--dry-run", action="store_true", help="Ne commit rien en base")
    p.add_argument("--fournisseur-nom", default="Foodex", help="Nom du fournisseur à créer/mettre à jour")
    return p


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(importer(pdf_path=args.pdf, dry_run=args.dry_run, fournisseur_nom=args.fournisseur_nom))


if __name__ == "__main__":
    main()
