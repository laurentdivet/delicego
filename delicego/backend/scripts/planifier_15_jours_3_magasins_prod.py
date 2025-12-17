from __future__ import annotations

"""Création des plans de production (J..J+14) pour 3 magasins (PROD), idempotent.

Règles :
- Utilise uniquement les services existants de planification (`ServicePlanificationProduction`)
- 1 plan par jour et par magasin
- Horizon: aujourd’hui + 14 jours (15 jours)
- Idempotent: si un plan existe déjà pour un magasin+date, on l’ignore
- Quantités constantes MVP :
    - 5 portions "Riz cantonais" (recette_id fourni)
    - 5 portions "Pad Thaï crevettes" (recette_id fourni)

Lancement:
    cd backend
    python -m scripts.planifier_15_jours_3_magasins_prod

"""

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.configuration import parametres_application
from app.domaine.modeles.production import LignePlanProduction, PlanProduction
from app.domaine.services.planifier_production import PlanProductionDejaExistant, ServicePlanificationProduction


@dataclass(frozen=True)
class MagasinCible:
    id: UUID
    nom: str


MAGASINS: list[MagasinCible] = [
    MagasinCible(UUID("0be7d9d5-8883-41b0-aff3-2dc6a77e76df"), "Carrefour Prigonrieux"),
    MagasinCible(UUID("3994db1d-af25-4141-a64f-27e74b411e0d"), "Carrefour Auguste Comte"),
    MagasinCible(UUID("60a4b99e-e2e3-4909-8b88-74acac5ca4a2"), "Intermarché Bergerac"),
]

RECETTE_RIZ_CANTONAIS_ID = UUID("281aa79e-dd52-4015-b534-6c97f454991f")
RECETTE_PAD_THAI_ID = UUID("c8372b4e-ffd4-4841-869e-438ec843f288")

QTE_RIZ = 5.0
QTE_PAD_THAI = 5.0

NB_JOURS = 15  # aujourd’hui + 14


async def _upsert_ligne(session, *, plan_id: UUID, recette_id: UUID, quantite: float) -> None:
    res = await session.execute(
        select(LignePlanProduction).where(
            LignePlanProduction.plan_production_id == plan_id,
            LignePlanProduction.recette_id == recette_id,
        )
    )
    ligne = res.scalar_one_or_none()
    if ligne is None:
        session.add(
            LignePlanProduction(
                plan_production_id=plan_id,
                recette_id=recette_id,
                quantite_a_produire=float(quantite),
            )
        )
        return

    ligne.quantite_a_produire = float(quantite)


async def _plan_existe(session, *, magasin_id: UUID, date_plan: date) -> bool:
    res = await session.execute(
        select(PlanProduction.id).where(
            PlanProduction.magasin_id == magasin_id,
            PlanProduction.date_plan == date_plan,
        )
    )
    return res.scalar_one_or_none() is not None


async def run() -> None:
    engine = create_async_engine(parametres_application.url_base_donnees, pool_pre_ping=True)
    sessionmaker_ = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Résumé
    nb_crees: dict[UUID, int] = {m.id: 0 for m in MAGASINS}
    nb_ignores: dict[UUID, int] = {m.id: 0 for m in MAGASINS}

    aujourd_hui = date.today()

    # IMPORTANT:
    # `ServicePlanificationProduction.planifier()` ouvre sa propre transaction via
    # `async with self._session.begin()`. Si nous faisons des SELECT avant dans la
    # même session, SQLAlchemy peut démarrer implicitement une transaction et le
    # service échoue avec "A transaction is already begun".
    #
    # => On évite l’état transactionnel partagé en utilisant 2 sessions distinctes :
    # - session_read: vérifie l’existence du plan
    # - session_write: appelle le service + upsert des lignes, puis commit

    # IMPORTANT bis:
    # Même `session_write` peut démarrer une transaction implicite lors de certaines
    # opérations, ce qui empêche ensuite `service.planifier()` d’ouvrir `begin()`.
    # Le plus robuste en script est d’utiliser une session *par plan*.

    async with sessionmaker_() as session_read:
        for magasin in MAGASINS:
            for offset in range(NB_JOURS):
                date_plan = aujourd_hui + timedelta(days=offset)

                if await _plan_existe(session_read, magasin_id=magasin.id, date_plan=date_plan):
                    nb_ignores[magasin.id] += 1
                    continue

                # Session dédiée à la création du plan
                async with sessionmaker_() as session_write:
                    service = ServicePlanificationProduction(session_write)

                    try:
                        plan = await service.planifier(
                            magasin_id=magasin.id,
                            date_plan=date_plan,
                            date_debut_historique=date_plan,
                            date_fin_historique=date_plan,
                            donnees_meteo={},
                            evenements=[],
                        )
                    except PlanProductionDejaExistant:
                        nb_ignores[magasin.id] += 1
                        continue

                    await _upsert_ligne(
                        session_write,
                        plan_id=plan.id,
                        recette_id=RECETTE_RIZ_CANTONAIS_ID,
                        quantite=QTE_RIZ,
                    )
                    await _upsert_ligne(
                        session_write,
                        plan_id=plan.id,
                        recette_id=RECETTE_PAD_THAI_ID,
                        quantite=QTE_PAD_THAI,
                    )

                    await session_write.commit()
                    nb_crees[magasin.id] += 1

    await engine.dispose()

    print("\n=== PLANIFICATION 15 JOURS: RÉSUMÉ ===")
    for m in MAGASINS:
        print(f"- {m.nom} ({m.id}) : plans créés={nb_crees[m.id]}, ignorés={nb_ignores[m.id]}")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
