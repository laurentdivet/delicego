from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domaine.modeles.referentiel import Ingredient, IngredientAlias


_RE_PARENS = re.compile(r"\([^)]*\)")
_RE_NUMBERS = re.compile(r"\d+")

# ponctuation (on conserve lettres/chiffres/espaces avant suppression chiffres)
_RE_PUNCT = re.compile(r"[^a-z0-9\s]+")

# unités -> on supprime uniquement en tant que mots entiers
_RE_UNITS = re.compile(r"\b(?:g|kg|ml|cl|l|%|mg)\b")

# unités collées au nombre (ex: 250g, 1kg, 20%)
_RE_NUM_UNIT = re.compile(r"\b\d+(?:[\.,]\d+)?\s*(?:g|kg|ml|cl|l|%|mg)\b")

_STOP_WORDS = {
    "frais",
    "fraiche",
    "fraiche",
    "haché",
    "hache",
    "hachée",
    "hachee",
    "émincé",
    "emince",
    "émincés",
    "eminces",
    "ciselé",
    "cisele",
    "bio",
    "surgelé",
    "surgele",
    "environ",
    "petit",
    "gros",
    "moyen",
}


def normalize_ingredient_label(label: str) -> str:
    """Normalise un libellé d'ingrédient pour faire du matching déterministe.

    Règles strictes (ordre appliqué):
    - minuscules
    - suppression accents
    - suppression contenu entre parenthèses
    - suppression ponctuation
    - suppression unités (g, kg, ml, cl, l, %, mg)
    - suppression chiffres
    - suppression mots parasites culinaires courants
    - normalisation espaces
    """

    s = (label or "").strip().lower()

    # retirer le contenu entre parenthèses
    s = _RE_PARENS.sub(" ", s)

    # supprimer accents
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))

    # ponctuation -> espaces
    s = _RE_PUNCT.sub(" ", s)

    # unités (y compris collées aux chiffres)
    s = _RE_NUM_UNIT.sub(" ", s)
    s = _RE_UNITS.sub(" ", s)

    # chiffres
    s = _RE_NUMBERS.sub(" ", s)

    # stop-words
    tokens = [t for t in re.split(r"\s+", s) if t]
    tokens = [t for t in tokens if t not in _STOP_WORDS]

    s = " ".join(tokens)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass(frozen=True)
class IngredientMatchResult:
    ingredient_id: UUID | None
    ingredient_nom: str | None
    matched_by: str | None  # 'alias' | 'ingredient' | None
    normalized_label: str


async def match_ingredient_id(
    session: AsyncSession,
    *,
    label_brut: str,
) -> IngredientMatchResult:
    """Matching strict d'un libellé brut vers Ingredient.

    Ordre strict:
    1) normaliser
    2) match exact sur IngredientAlias.alias_normalise (actif=true)
    3) sinon match exact sur Ingredient.nom (normalisé en mémoire) (actif=true)
    4) sinon non mappé

    Note: le schéma existant n'a pas de Ingredient.nom_normalise.
    Hypothèse raisonnable: on applique la même normalisation au champ Ingredient.nom
    au moment du matching (d'où le besoin d'indexer alias_normalise pour la perf).
    """

    normalized = normalize_ingredient_label(label_brut)

    if not normalized:
        return IngredientMatchResult(
            ingredient_id=None,
            ingredient_nom=None,
            matched_by=None,
            normalized_label=normalized,
        )

    res = await session.execute(
        select(IngredientAlias).where(
            IngredientAlias.alias_normalise == normalized,
            IngredientAlias.actif.is_(True),
        )
    )
    alias = res.scalar_one_or_none()
    if alias is not None:
        return IngredientMatchResult(
            ingredient_id=alias.ingredient_id,
            ingredient_nom=alias.ingredient.nom,
            matched_by="alias",
            normalized_label=normalized,
        )

    # fallback exact sur ingredient.nom normalisé
    res = await session.execute(select(Ingredient).where(Ingredient.actif.is_(True)))
    for ing in res.scalars().all():
        if normalize_ingredient_label(ing.nom) == normalized:
            return IngredientMatchResult(
                ingredient_id=ing.id,
                ingredient_nom=ing.nom,
                matched_by="ingredient",
                normalized_label=normalized,
            )

    return IngredientMatchResult(
        ingredient_id=None,
        ingredient_nom=None,
        matched_by=None,
        normalized_label=normalized,
    )


async def build_ingredient_normalized_index(session: AsyncSession) -> dict[str, UUID]:
    """Construit un index en mémoire {nom_normalise: ingredient_id}.

    Contrainte explicite: on ne crée PAS de colonne ingredient.nom_normalise.
    On calcule une fois pour éviter la normalisation répétée.
    """

    res = await session.execute(select(Ingredient.id, Ingredient.nom).where(Ingredient.actif.is_(True)))
    index: dict[str, UUID] = {}
    for ing_id, nom in res.all():
        key = normalize_ingredient_label(nom)
        if not key:
            continue
        # Si collision, on ne mappe pas via ce fallback (sécurité)
        if key in index and index[key] != ing_id:
            index.pop(key, None)
            continue
        index[key] = ing_id
    return index


async def match_ingredient_id_with_index(
    session: AsyncSession,
    *,
    label_brut: str,
    ingredient_index: dict[str, UUID],
) -> IngredientMatchResult:
    """Même logique que match_ingredient_id, mais avec fallback optimisé via index."""

    normalized = normalize_ingredient_label(label_brut)
    if not normalized:
        return IngredientMatchResult(None, None, None, normalized)

    res = await session.execute(
        select(IngredientAlias).where(
            IngredientAlias.alias_normalise == normalized,
            IngredientAlias.actif.is_(True),
        )
    )
    alias = res.scalar_one_or_none()
    if alias is not None:
        return IngredientMatchResult(alias.ingredient_id, alias.ingredient.nom, "alias", normalized)

    ing_id = ingredient_index.get(normalized)
    if ing_id is not None:
        return IngredientMatchResult(ing_id, None, "ingredient", normalized)

    return IngredientMatchResult(None, None, None, normalized)
