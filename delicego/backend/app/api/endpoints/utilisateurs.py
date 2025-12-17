from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session
from app.api.dependances_auth import verifier_roles_requis
from app.api.schemas.auth import UserCreation, UserLecture, UserMiseAJour
from app.core.securite import hasher_mot_de_passe
from app.domaine.modeles.auth import Role, User, UserRole


routeur_utilisateurs = APIRouter(
    prefix="/api/interne/utilisateurs",
    tags=["utilisateurs_interne"],
    dependencies=[Depends(verifier_roles_requis("manager"))],
)


async def _roles_codes_par_user_id(session: AsyncSession, user_id: UUID) -> list[str]:
    res = await session.execute(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return [r[0] for r in res.all()]


@routeur_utilisateurs.get("", response_model=list[UserLecture])
async def lister_utilisateurs(session: AsyncSession = Depends(fournir_session)) -> list[UserLecture]:
    res = await session.execute(select(User).order_by(User.email.asc()))
    users = res.scalars().all()

    resultat: list[UserLecture] = []
    for u in users:
        roles = await _roles_codes_par_user_id(session, u.id)
        resultat.append(
            UserLecture(
                id=str(u.id),
                email=u.email,
                nom_affiche=u.nom_affiche,
                actif=u.actif,
                roles=roles,
            )
        )

    return resultat


@routeur_utilisateurs.post("", response_model=UserLecture, status_code=status.HTTP_201_CREATED)
async def creer_utilisateur(
    requete: UserCreation,
    session: AsyncSession = Depends(fournir_session),
) -> UserLecture:
    existe = await session.execute(select(User).where(User.email == requete.email))
    if existe.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email déjà utilisé.")

    user = User(
        email=requete.email,
        nom_affiche=requete.nom_affiche,
        mot_de_passe_hash=hasher_mot_de_passe(requete.mot_de_passe),
        actif=True,
    )
    session.add(user)
    await session.flush()  # obtenir user.id

    # Associer les rôles (par code)
    if requete.roles:
        roles_db = await session.execute(select(Role).where(Role.code.in_(requete.roles)))
        roles = roles_db.scalars().all()
        codes = {r.code for r in roles}
        inconnus = [c for c in requete.roles if c not in codes]
        if inconnus:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Rôles inconnus: {inconnus}")

        for r in roles:
            session.add(UserRole(user_id=user.id, role_id=r.id))

    await session.commit()

    roles = await _roles_codes_par_user_id(session, user.id)
    return UserLecture(id=str(user.id), email=user.email, nom_affiche=user.nom_affiche, actif=user.actif, roles=roles)


@routeur_utilisateurs.patch("/{user_id}", response_model=UserLecture)
async def maj_utilisateur(
    user_id: UUID,
    requete: UserMiseAJour,
    session: AsyncSession = Depends(fournir_session),
) -> UserLecture:
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable.")

    if requete.nom_affiche is not None:
        user.nom_affiche = requete.nom_affiche
    if requete.actif is not None:
        user.actif = requete.actif

    if requete.roles is not None:
        # reset roles
        await session.execute(delete(UserRole).where(UserRole.user_id == user_id))

        if requete.roles:
            roles_db = await session.execute(select(Role).where(Role.code.in_(requete.roles)))
            roles = roles_db.scalars().all()
            codes = {r.code for r in roles}
            inconnus = [c for c in requete.roles if c not in codes]
            if inconnus:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Rôles inconnus: {inconnus}")
            for r in roles:
                session.add(UserRole(user_id=user_id, role_id=r.id))

    await session.commit()

    roles = await _roles_codes_par_user_id(session, user.id)
    return UserLecture(id=str(user.id), email=user.email, nom_affiche=user.nom_affiche, actif=user.actif, roles=roles)


@routeur_utilisateurs.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def desactiver_utilisateur(
    user_id: UUID,
    session: AsyncSession = Depends(fournir_session),
) -> dict[str, str]:
    res = await session.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable.")

    # On ne supprime pas : on désactive (sûr pour l’audit)
    user.actif = False
    await session.commit()
    return {"statut": "ok"}
