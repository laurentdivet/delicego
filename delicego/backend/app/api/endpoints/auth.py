from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.api.dependances_auth import fournir_utilisateur_courant
from app.api.schemas.auth import ReponseLogin, RequeteLogin
from app.core.configuration import parametres_application
from app.core.securite import creer_token_acces, verifier_mot_de_passe
from app.domaine.modeles.auth import Role, User, UserRole


routeur_auth = APIRouter(prefix="/auth", tags=["auth"])


@routeur_auth.get("/me")
async def me(
    user: User = Depends(fournir_utilisateur_courant),
    session: AsyncSession = Depends(fournir_session),
) -> dict:
    """Infos utilisateur courant (debug/UX).

    Retour volontairement minimal, sans exposer le hash.
    """

    roles_res = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    roles = [r[0] for r in roles_res.all()]

    return {
        "id": str(user.id),
        "email": user.email,
        "nom_affiche": user.nom_affiche,
        "actif": user.actif,
        "roles": roles,
    }


@routeur_auth.post("/login", response_model=ReponseLogin)
async def login(requete: RequeteLogin, session: AsyncSession = Depends(fournir_session)) -> ReponseLogin:
    res = await session.execute(select(User).where(User.email == requete.email))
    user = res.scalar_one_or_none()
    if user is None or not user.actif:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides.")

    if not verifier_mot_de_passe(requete.mot_de_passe, user.mot_de_passe_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides.")

    roles_res = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    roles = [r[0] for r in roles_res.all()]

    user.dernier_login_le = datetime.now(tz=timezone.utc)
    await session.commit()

    token = creer_token_acces(
        secret=parametres_application.jwt_secret,
        sujet=str(user.id),
        duree_minutes=parametres_application.jwt_duree_minutes,
        roles=roles,
    )

    return ReponseLogin(token_acces=token)
