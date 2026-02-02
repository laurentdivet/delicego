from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession


class ErreurCritiqueMetier(Exception):
    """Erreur métier critique : doit être affichée clairement à l'utilisateur."""


async def executer_transaction(
    session: AsyncSession,
    *,
    action: Callable[[], Awaitable[object]],
) -> object:
    """Wrapper transactionnel: rollback + remontée d'erreur claire.

    Utilisation typique dans un endpoint:

        try:
            res = await executer_transaction(session, action=lambda: svc.executer(...))
        except ErreurCritiqueMetier as e:
            raise HTTPException(status_code=400, detail=str(e))
    """

    try:
        async with session.begin():
            return await action()
    except ErreurCritiqueMetier:
        # session.begin() fait rollback automatiquement en cas d'exception.
        raise
