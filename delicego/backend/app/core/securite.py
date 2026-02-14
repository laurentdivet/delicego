"""
Sécurité : hashing des mots de passe + création/validation de JWT.

IMPORTANT
- Aucun bypass "test" n'est autorisé dans ce module.
- Le hashing tente bcrypt en priorité, avec fallback pbkdf2_sha256 si bcrypt n'est pas dispo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from passlib.exc import MissingBackendError

# bcrypt en priorité; fallback en cas d'environnement cassé (ex: bcrypt backend manquant)
_pwd_context = CryptContext(
    schemes=["bcrypt", "pbkdf2_sha256"],
    deprecated="auto",
)


def _as_str(x: Any) -> str:
    if isinstance(x, str):
        return x
    raise ValueError("valeur invalide (str attendue)")


def hasher_mot_de_passe(mot_de_passe: str) -> str:
    """
    Retourne le hash du mot de passe.

    Stratégie:
    - essaie bcrypt
    - si bcrypt indisponible (backend manquant) OU si secret > 72 bytes (limite bcrypt),
      on retombe sur pbkdf2_sha256
    """
    mot_de_passe = _as_str(mot_de_passe).strip()
    if not mot_de_passe:
        raise ValueError("mot_de_passe invalide")

    # Limite bcrypt: 72 bytes (pas caractères)
    # -> si trop long, on force pbkdf2_sha256 (sinon ValueError en runtime)
    if len(mot_de_passe.encode("utf-8")) > 72:
        return _pwd_context.hash(mot_de_passe, scheme="pbkdf2_sha256")

    try:
        # essaie "normal" (bcrypt en premier)
        return _pwd_context.hash(mot_de_passe)
    except (MissingBackendError, AttributeError, ValueError):
        # - MissingBackendError: backend bcrypt absent
        # - AttributeError: certains combos passlib/bcrypt foireux
        # - ValueError: edge cases bcrypt
        return _pwd_context.hash(mot_de_passe, scheme="pbkdf2_sha256")


def verifier_mot_de_passe(mot_de_passe: str, mot_de_passe_hash: str) -> bool:
    """Vérifie un mot de passe en clair contre un hash."""
    try:
        mot_de_passe = _as_str(mot_de_passe)
        mot_de_passe_hash = _as_str(mot_de_passe_hash)
    except ValueError:
        return False

    if not mot_de_passe_hash:
        return False

    try:
        return _pwd_context.verify(mot_de_passe, mot_de_passe_hash)
    except Exception:
        # hash corrompu, algo non supporté, etc.
        return False


def creer_token_acces(
    sujet: str,
    *,
    roles: list[str] | None = None,
    # compat legacy utilisée par des tests / vieux appels
    duree_minutes: int | None = None,
    # standard
    expires_delta: timedelta | None = None,
    secret: str,
    algorithm: str = "HS256",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Crée un JWT d'accès.

    - sujet: identifiant utilisateur (id / email / uuid string)
    - roles: liste de rôles (optionnel)
    - duree_minutes: compat legacy (optionnel)
    - expires_delta: durée de validité (optionnel)
    - secret: secret de signature (OBLIGATOIRE)

    Règles:
    - si expires_delta est fourni, il prime
    - sinon, si duree_minutes est fourni, il est converti en timedelta
    - sinon, durée par défaut = 60 minutes
    """
    sujet = _as_str(sujet).strip()
    if not sujet:
        raise ValueError("sujet JWT manquant")
    if not secret:
        raise ValueError("secret JWT manquant")

    if expires_delta is None and duree_minutes is not None:
        if not isinstance(duree_minutes, int) or duree_minutes <= 0:
            raise ValueError("duree_minutes invalide")
        expires_delta = timedelta(minutes=duree_minutes)

    now = datetime.now(UTC)
    exp = now + (expires_delta or timedelta(minutes=60))

    payload: dict[str, Any] = {
        "sub": sujet,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if roles is not None:
        payload["roles"] = roles
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, secret, algorithm=algorithm)


def decoder_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
) -> dict[str, Any]:
    """Décode et valide un JWT, lève ValueError si invalide."""
    token = _as_str(token).strip()
    if not token:
        raise ValueError("token manquant")
    if not secret:
        raise ValueError("secret JWT manquant")

    try:
        data = jwt.decode(token, secret, algorithms=[algorithm])
    except JWTError as e:
        raise ValueError("token invalide") from e

    if not isinstance(data, dict):
        raise ValueError("payload JWT invalide")

    # garde-fous minimaux
    sub = data.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise ValueError("payload JWT invalide (sub)")

    return data


# --- Aliases de compat (le reste du code les importe déjà) ---

def decoder_token_acces(token: str, *, secret: str, algorithm: str = "HS256") -> dict[str, Any]:
    """Alias de compat : decoder_token_acces -> decoder_token."""
    return decoder_token(token, secret=secret, algorithm=algorithm)


def creer_token(*args: Any, **kwargs: Any) -> str:
    """Alias de compat : creer_token -> creer_token_acces."""
    return creer_token_acces(*args, **kwargs)
