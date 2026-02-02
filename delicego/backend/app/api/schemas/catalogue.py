from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ProduitCreate(BaseModel):
    libelle: str = Field(..., min_length=1, max_length=250)
    categorie: str | None = Field(default=None, max_length=120)
    actif: bool = True


class ProduitUpdate(BaseModel):
    libelle: str | None = Field(default=None, min_length=1, max_length=250)
    categorie: str | None = Field(default=None, max_length=120)
    actif: bool | None = None


class ProduitOut(BaseModel):
    id: UUID
    libelle: str
    categorie: str | None
    actif: bool

    class Config:
        from_attributes = True


class ProduitMini(BaseModel):
    id: UUID
    libelle: str

    class Config:
        from_attributes = True


class ProduitFournisseurCreate(BaseModel):
    fournisseur_id: UUID
    produit_id: UUID
    reference_fournisseur: str = Field(..., min_length=1, max_length=120)
    libelle_fournisseur: str | None = Field(default=None, max_length=250)
    unite_achat: str = Field(..., min_length=1, max_length=50)
    quantite_par_unite: float = Field(default=1.0, gt=0)
    prix_achat_ht: float | None = None
    tva: float | None = None
    actif: bool = True


class ProduitFournisseurUpdate(BaseModel):
    produit_id: UUID | None = None
    reference_fournisseur: str | None = Field(default=None, min_length=1, max_length=120)
    libelle_fournisseur: str | None = Field(default=None, max_length=250)
    unite_achat: str | None = Field(default=None, min_length=1, max_length=50)
    quantite_par_unite: float | None = Field(default=None, gt=0)
    prix_achat_ht: float | None = None
    tva: float | None = None
    actif: bool | None = None


class ProduitFournisseurOut(BaseModel):
    id: UUID
    fournisseur_id: UUID
    produit_id: UUID
    reference_fournisseur: str
    libelle_fournisseur: str | None
    unite_achat: str
    quantite_par_unite: float
    prix_achat_ht: float | None
    tva: float | None
    actif: bool
    produit: ProduitMini

    class Config:
        from_attributes = True
