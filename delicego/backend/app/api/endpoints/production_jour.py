from __future__ import annotations

"""Endpoint interne: Production du jour (end-to-end).

Route
-----
POST /api/interne/operations/production-du-jour

Payload:
{
  "magasin_id": "<uuid>",
  "date_jour": "YYYY-MM-DD",
  "lignes": [
    {"recette_id": "<uuid>", "quantite_a_produire": 12},
    ...
  ]
}

Réponse:
{
  "plan_id": "...",
  "lots_crees": 2,
  "consommations_creees": 10,
  "mouvements_stock_crees": 10,
  "besoins": [],
  "warnings": []
}

Erreurs:
- 400: validation payload
- 401/403: auth/roles
- 409: stock insuffisant

Exemples curl
------------

Happy path:

curl -X POST "http://localhost:8000/api/interne/operations/production-du-jour" \
  -H "Content-Type: application/json" \
  -H "X-CLE-INTERNE: dev" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "magasin_id": "00000000-0000-0000-0000-000000000000",
    "date_jour": "2026-02-02",
    "lignes": [
      {"recette_id": "00000000-0000-0000-0000-000000000001", "quantite_a_produire": 12}
    ]
  }'

Stock insuffisant (attendu 409):

curl -i -X POST "http://localhost:8000/api/interne/operations/production-du-jour" \
  -H "Content-Type: application/json" \
  -H "X-CLE-INTERNE: dev" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "magasin_id": "00000000-0000-0000-0000-000000000000",
    "date_jour": "2026-02-02",
    "lignes": [
      {"recette_id": "00000000-0000-0000-0000-000000000001", "quantite_a_produire": 999999}
    ]
  }'
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependances import fournir_session, verifier_acces_interne
from app.api.dependances_auth import verifier_authentifie, verifier_roles_requis_legacy
from app.api.schemas.production_jour import ReponseProductionDuJour, RequeteProductionDuJour
from app.domaine.services.production_jour_service import (
    DonneesInvalidesProductionJour,
    LigneProductionJour,
    ServiceProductionJour,
    StockInsuffisantProductionJour,
)


routeur_production_jour_interne = APIRouter(
    prefix="/operations",
    tags=["operations_interne"],
    dependencies=[
        Depends(verifier_acces_interne),
        Depends(verifier_authentifie),
        Depends(verifier_roles_requis_legacy("admin", "operateur")),
    ],
)


@routeur_production_jour_interne.post(
    "/production-du-jour",
    response_model=ReponseProductionDuJour,
    status_code=status.HTTP_201_CREATED,
)
async def produire_du_jour(
    requete: RequeteProductionDuJour,
    session: AsyncSession = Depends(fournir_session),
) -> ReponseProductionDuJour:
    service = ServiceProductionJour(session)

    try:
        resultat = await service.executer_production_du_jour(
            magasin_id=requete.magasin_id,
            date_jour=requete.date_jour,
            lignes=[
                LigneProductionJour(recette_id=l.recette_id, quantite_a_produire=l.quantite_a_produire)
                for l in requete.lignes
            ],
        )
    except DonneesInvalidesProductionJour as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except StockInsuffisantProductionJour as e:
        # Conflit: la demande n'est pas applicable compte tenu du stock actuel.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    return ReponseProductionDuJour(
        plan_id=resultat.plan_production_id,
        lots_crees=len(resultat.lots_production_ids),
        consommations_creees=resultat.nb_lignes_consommation,
        mouvements_stock_crees=resultat.nb_mouvements_stock,
        besoins=[],
        warnings=[],
    )
