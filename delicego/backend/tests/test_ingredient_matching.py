from __future__ import annotations

import pytest

from app.domaine.services.ingredient_matching import normalize_ingredient_label


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Tomates (fraîches) 250g", "tomates"),
        ("Crème fraîche 20% 30 cl", "creme"),
        ("Oignons émincés 2", "oignons"),
        ("PERSIL ciselé", "persil"),
        ("  Poulet-bio (haché) 1kg ", "poulet"),
        ("", ""),
    ],
)
def test_normalize_ingredient_label(raw: str, expected: str) -> None:
    assert normalize_ingredient_label(raw) == expected
