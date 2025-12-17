from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RequeteLogin(BaseModel):
    email: EmailStr
    mot_de_passe: str = Field(min_length=8)


class ReponseLogin(BaseModel):
    token_acces: str
    type_token: str = "bearer"


class UserLecture(BaseModel):
    id: str
    email: EmailStr
    nom_affiche: str
    actif: bool
    roles: list[str]


class UserCreation(BaseModel):
    email: EmailStr
    nom_affiche: str
    mot_de_passe: str = Field(min_length=8)
    roles: list[str] = Field(default_factory=list)


class UserMiseAJour(BaseModel):
    nom_affiche: str | None = None
    actif: bool | None = None
    roles: list[str] | None = None
