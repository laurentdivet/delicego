"""Helpers d'auth STRICTEMENT côté tests.

Objectif: éviter de dépendre de passlib/bcrypt dans les tests (lib manquante,
limite 72 bytes, etc.) tout en gardant un champ `mot_de_passe_hash` cohérent.
"""

# Hash bcrypt "valide" (format) mais constant. Ne pas utiliser en prod.
FAKE_BCRYPT_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO5H/1h9WlH0I1d9YxwE8VqQX2E7p.5W2"
