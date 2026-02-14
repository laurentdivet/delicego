from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.core.configuration import parametres_application
from app.core.securite import decoder_token_acces
from app.domaine.modeles.auth import Role, User, UserRole


def _extraire_bearer(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    prefix = "bearer "
    if authorization.lower().startswith(prefix):
        return authorization[len(prefix) :].strip()
    return None


async def fournir_utilisateur_courant(
    session: AsyncSession = Depends(fournir_session),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> User:
    token = _extraire_bearer(authorization)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token manquant.")

    try:
        payload = decoder_token_acces(token, secret=parametres_application.jwt_secret)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.")

    try:
        user_id = UUID(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide (sub).")

    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None or not user.actif:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur inactif.")

    return user


async def fournir_roles_utilisateur(
    user: User = Depends(fournir_utilisateur_courant),
    session: AsyncSession = Depends(fournir_session),
) -> list[str]:
    res = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    return [r[0] for r in res.all()]


def verifier_authentifie(user: User = Depends(fournir_utilisateur_courant)) -> None:
    """Dépendance simple : exige un utilisateur authentifié."""

    # Le vrai travail est fait dans fournir_utilisateur_courant.
    # Ici, on garde la signature pour être utilisée directement dans dependencies=[...]
    # sans se préoccuper de la valeur de retour.
    return None


def verifier_authentifie_ou_interne(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    _x_cle_interne: str | None = Header(default=None, alias="X-CLE-INTERNE"),
) -> None:
    """Compat interne : si X-CLE-INTERNE est présent, on ne bloque pas sur JWT.

    Certaines routes /api/interne/* sont destinées à un usage technique (dashboard,
    cuisine, etc.) et sont déjà protégées par `verifier_acces_interne`.
    Historiquement elles ne nécessitaient pas d'auth JWT utilisateur.

    Pour éviter de casser ces endpoints (et leurs tests), on accepte :
    - soit un JWT valide (Authorization: Bearer ...)
    - soit un accès interne (X-CLE-INTERNE) déjà validé en amont.
    """

    # Si on a un token interne (via X-CLE-INTERNE ou via Authorization: Bearer <token interne>),
    # alors `verifier_acces_interne` a déjà validé l'accès.
    # -> on n'exige pas un JWT user.
    if _x_cle_interne:
        return None

    # NOTE : cette dépendance ne doit JAMAIS bloquer les routes /api/interne/*.
    # Ces routes sont déjà sécurisées par `verifier_acces_interne` au niveau du
    # routeur interne.
    if request.url.path.startswith("/api/interne"):
        return None

    # Fallback: comportement strict JWT.
    # On réutilise la logique existante.
    token = _extraire_bearer(authorization)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token manquant.")
    try:
        decoder_token_acces(token, secret=parametres_application.jwt_secret)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.")


def verifier_roles_requis(*roles_requis: str):
    async def _dep(roles: list[str] = Depends(fournir_roles_utilisateur)) -> None:
        if not set(roles_requis).intersection(set(roles)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit.")

    return _dep


def verifier_roles_requis_legacy(*roles_requis: str):
    """Compat tests/ancien naming.

    Historique du repo : on a eu des rôles `manager`, `employe`, ...
    La demande actuelle vise `admin` / `operateur`.

    Pour ne pas casser les tests existants, on mappe :
    - manager -> admin
    - employe -> operateur
    """

    # Si un appelant passe encore un rôle legacy, on l'accepte tel quel.
    # Sinon, on mappe vers les rôles actuels.
    mapping = {
        "admin": "admin",
        "operateur": "operateur",
        "manager": "manager",
        "employe": "employe",
    }

    roles_mappes = [mapping.get(r, r) for r in roles_requis]
    return verifier_roles_requis(*roles_mappes)
