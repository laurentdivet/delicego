from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext


_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hasher_mot_de_passe(mot_de_passe: str) -> str:
    return _pwd_context.hash(mot_de_passe)


def verifier_mot_de_passe(mot_de_passe: str, mot_de_passe_hash: str) -> bool:
    return _pwd_context.verify(mot_de_passe, mot_de_passe_hash)


def creer_token_acces(
    *,
    secret: str,
    sujet: str,
    duree_minutes: int,
    roles: list[str],
) -> str:
    maintenant = datetime.now(tz=timezone.utc)
    expire_le = maintenant + timedelta(minutes=duree_minutes)

    payload = {
        "sub": sujet,
        "iat": int(maintenant.timestamp()),
        "exp": int(expire_le.timestamp()),
        "roles": roles,
    }

    return jwt.encode(payload, secret, algorithm="HS256")


def decoder_token_acces(token: str, *, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])
