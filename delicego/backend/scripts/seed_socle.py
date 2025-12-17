from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.base_donnees import fournir_session_async
from app.core.securite import hasher_mot_de_passe
from app.domaine.modeles.auth import Role, User, UserRole


ROLES = [
    ("manager", "Manager"),
    ("employe", "Employé"),
    ("qualite", "Qualité"),
]


async def seed() -> None:
    async for session in fournir_session_async():
        # roles
        for code, libelle in ROLES:
            res = await session.execute(select(Role).where(Role.code == code))
            if res.scalar_one_or_none() is None:
                session.add(Role(code=code, libelle=libelle, actif=True))

        await session.commit()

        # manager par défaut
        email = "admin@delicego.local"
        res = await session.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                nom_affiche="Admin",
                mot_de_passe_hash=hasher_mot_de_passe("ChangeMe123!"),
                actif=True,
            )
            session.add(user)
            await session.flush()

        role_manager = (await session.execute(select(Role).where(Role.code == "manager"))).scalar_one()

        # assoc role si pas déjà
        res = await session.execute(
            select(UserRole).where(UserRole.user_id == user.id).where(UserRole.role_id == role_manager.id)
        )
        if res.scalar_one_or_none() is None:
            session.add(UserRole(user_id=user.id, role_id=role_manager.id))

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
