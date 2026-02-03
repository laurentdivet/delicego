from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ParametresApplication(BaseSettings):
    """Paramètres de l’application.

    Tout est volontairement minimal : on ne fournit pas de CLI et on ne
    publie pas d’API métier.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    url_base_donnees: str = "postgresql+asyncpg://delicego:delicego@localhost:5433/delicego"

    # ===== Impact KPIs =====
    # Seuil (km) pour considérer un fournisseur comme "local".
    impact_local_km_threshold: float = 100.0

    jwt_secret: str = "CHANGE_ME"
    jwt_duree_minutes: int = 60 * 12


parametres_application = ParametresApplication()
