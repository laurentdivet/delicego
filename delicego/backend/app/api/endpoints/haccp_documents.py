from __future__ import annotations

"""Endpoints Gestion documentaire HACCP.

API STRICTE:
- POST /documents/upload
- POST /documents/{id}/validate
- GET /documents
- GET /documents/{id}/download

Stockage fichiers: local backend/storage/haccp/
"""

from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.schemas.haccp_documents import DocumentReadSchema, DocumentUploadResponse, DocumentValidateResponse
from app.domaine.modeles.haccp_documents import (
    Document,
    ImmutableAfterValidationError,
    InMemoryDocumentsRepo,
    NotFoundError,
    ValidationError,
)


routeur_haccp_documents = APIRouter(prefix="/documents", tags=["haccp-documents"])

# stockage local
_STORAGE_DIR = Path(__file__).resolve().parents[4] / "storage" / "haccp"
_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# repo in-memory (process)
_REPO = InMemoryDocumentsRepo()


def _require_uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{field} invalide") from e


@routeur_haccp_documents.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: Annotated[UploadFile, File(...)],
    category_id: Annotated[str, Form(...)],
    etablissement_id: Annotated[str, Form(...)],
    uploaded_by: Annotated[str, Form(...)],
) -> DocumentUploadResponse:
    # Règle: toute action liée à un utilisateur + établissement
    cat_id = _require_uuid(category_id, "category_id")
    eta_id = _require_uuid(etablissement_id, "etablissement_id")
    user_id = _require_uuid(uploaded_by, "uploaded_by")

    if file.filename is None or file.filename.strip() == "":
        raise HTTPException(status_code=400, detail="filename obligatoire")

    doc_id = uuid4()
    # Pas de modification de fichier après upload => on écrit une fois et chemin figé
    safe_name = file.filename.replace("/", "_")
    target = _STORAGE_DIR / f"{doc_id}_{safe_name}"

    try:
        content = await file.read()
        target.write_bytes(content)

        doc = Document(
            id=doc_id,
            category_id=cat_id,
            etablissement_id=eta_id,
            filename=safe_name,
            filepath=str(target),
            uploaded_by=user_id,
            validated=False,
        )
        _REPO.add_document(doc)
        return DocumentUploadResponse(id=doc.id)

    except (ValidationError, NotFoundError, ImmutableAfterValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@routeur_haccp_documents.post("/{doc_id}/validate", response_model=DocumentValidateResponse)
async def validate_document(doc_id: UUID, uploaded_by: str = Form(...)) -> DocumentValidateResponse:
    user_id = _require_uuid(uploaded_by, "uploaded_by")
    try:
        doc = _REPO.validate(doc_id, user_id=user_id)
        return DocumentValidateResponse(id=doc.id, validated=doc.validated)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="not found")
    except (ValidationError, ImmutableAfterValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@routeur_haccp_documents.get("", response_model=list[DocumentReadSchema])
async def list_documents(etablissement_id: str | None = None) -> list[DocumentReadSchema]:
    eta_id = _require_uuid(etablissement_id, "etablissement_id") if etablissement_id else None
    docs = _REPO.list(etablissement_id=eta_id)
    return [DocumentReadSchema.model_validate(d.__dict__) for d in docs]


@routeur_haccp_documents.get("/{doc_id}/download")
async def download_document(doc_id: UUID) -> FileResponse:
    try:
        doc = _REPO.get(doc_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="not found")

    path = Path(doc.filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")

    return FileResponse(path=str(path), filename=doc.filename)
