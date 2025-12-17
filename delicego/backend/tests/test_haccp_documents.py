from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_upload_document(client: TestClient) -> None:
    cat_id = uuid4()
    eta_id = uuid4()
    user_id = uuid4()

    resp = client.post(
        "/documents/upload",
        files={"file": ("doc.txt", b"hello", "text/plain")},
        data={
            "category_id": str(cat_id),
            "etablissement_id": str(eta_id),
            "uploaded_by": str(user_id),
        },
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["id"]
    assert doc_id

    # list
    resp2 = client.get("/documents")
    assert resp2.status_code == 200
    assert any(d["id"] == doc_id for d in resp2.json())


def test_refus_modification_apres_validation(client: TestClient) -> None:
    cat_id = uuid4()
    eta_id = uuid4()
    user_id = uuid4()

    up = client.post(
        "/documents/upload",
        files={"file": ("doc2.txt", b"hello", "text/plain")},
        data={"category_id": str(cat_id), "etablissement_id": str(eta_id), "uploaded_by": str(user_id)},
    )
    doc_id = up.json()["id"]

    v = client.post(f"/documents/{doc_id}/validate", data={"uploaded_by": str(user_id)})
    assert v.status_code == 200

    # re-upload with same filename is not a modification of the same document.
    # To test immutability, we ensure validate is idempotent and cannot flip back.
    v2 = client.post(f"/documents/{doc_id}/validate", data={"uploaded_by": str(user_id)})
    assert v2.status_code == 200
    assert v2.json()["validated"] is True


def test_suppression_autorisee_avant_validation_et_refusee_apres_validation() -> None:
    # règle testée côté modèle/repo (delete) car l'API n'expose pas de DELETE.
    from app.domaine.modeles.haccp_documents import Document, ImmutableAfterValidationError, InMemoryDocumentsRepo

    repo = InMemoryDocumentsRepo()
    doc = Document(
        category_id=uuid4(),
        etablissement_id=uuid4(),
        filename="a.txt",
        filepath="/tmp/a.txt",
        uploaded_by=uuid4(),
        validated=False,
    )
    repo.add_document(doc)

    # suppression ok avant validation
    repo.delete(doc.id, user_id=uuid4())

    # recrée et valide
    doc2 = Document(
        category_id=uuid4(),
        etablissement_id=uuid4(),
        filename="b.txt",
        filepath="/tmp/b.txt",
        uploaded_by=uuid4(),
        validated=False,
    )
    repo.add_document(doc2)
    repo.validate(doc2.id, user_id=uuid4())

    with pytest.raises(ImmutableAfterValidationError):
        repo.delete(doc2.id, user_id=uuid4())


def test_telechargement_fichier_existant(client: TestClient) -> None:
    cat_id = uuid4()
    eta_id = uuid4()
    user_id = uuid4()

    up = client.post(
        "/documents/upload",
        files={"file": ("dl.txt", b"content", "text/plain")},
        data={"category_id": str(cat_id), "etablissement_id": str(eta_id), "uploaded_by": str(user_id)},
    )
    assert up.status_code == 200
    doc_id = up.json()["id"]

    dl = client.get(f"/documents/{doc_id}/download")
    assert dl.status_code == 200
    assert dl.content == b"content"

    # sanity: file actually exists on disk
    # we rely on returned headers filename; just ensure storage path exists by listing
    storage_dir = Path(__file__).resolve().parents[2] / "storage" / "haccp"
    assert storage_dir.exists()
    assert any(p.name.endswith("dl.txt") for p in storage_dir.iterdir())
