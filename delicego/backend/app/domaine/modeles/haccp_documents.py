from __future__ import annotations

"""Gestion documentaire HACCP (simple et opposable).

Contraintes: ce module est autonome et ne dépend pas des modules HACCP core,
stocks, production, analytics.

Stockage des fichiers: local (ex: backend/storage/haccp/)

Règles métier:
- Un document validé est IMMUTABLE
- Un document non validé peut être supprimé
- Toute action est liée à un utilisateur
- Les documents sont liés à un établissement
- Pas de modification de fichier après upload

NB: ce module fournit des entités in-memory et une petite "repository" in-memory
pour permettre les tests et l'API sans DB.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID, uuid4


class HaccpDocumentsError(ValueError):
    pass


class ValidationError(HaccpDocumentsError):
    pass


class ImmutableAfterValidationError(HaccpDocumentsError):
    pass


class NotFoundError(HaccpDocumentsError):
    pass


@dataclass(frozen=True)
class DocumentCategory:
    id: UUID = field(default_factory=uuid4)
    nom: str = ""


@dataclass(frozen=True)
class Document:
    id: UUID = field(default_factory=uuid4)

    category_id: UUID = field(default_factory=uuid4)
    etablissement_id: UUID = field(default_factory=uuid4)

    filename: str = ""
    filepath: str = ""

    uploaded_at: datetime = field(default_factory=datetime.utcnow)
    uploaded_by: UUID = field(default_factory=uuid4)

    validated: bool = False

    def validate(self) -> "Document":
        if self.validated:
            return self
        return replace(self, validated=True)

    def assert_mutable(self) -> None:
        if self.validated:
            raise ImmutableAfterValidationError("Document validé: immutable")


class InMemoryDocumentsRepo:
    def __init__(self) -> None:
        self._docs: dict[UUID, Document] = {}
        self._categories: dict[UUID, DocumentCategory] = {}

    # Categories (minimales)
    def add_category(self, cat: DocumentCategory) -> DocumentCategory:
        if not cat.nom or cat.nom.strip() == "":
            raise ValidationError("nom catégorie obligatoire")
        self._categories[cat.id] = cat
        return cat

    def list_categories(self) -> list[DocumentCategory]:
        return list(self._categories.values())

    # Documents
    def add_document(self, doc: Document) -> Document:
        if not doc.filename or doc.filename.strip() == "":
            raise ValidationError("filename obligatoire")
        if not doc.filepath or doc.filepath.strip() == "":
            raise ValidationError("filepath obligatoire")
        if doc.uploaded_by is None:
            raise ValidationError("uploaded_by obligatoire")
        if doc.etablissement_id is None:
            raise ValidationError("etablissement_id obligatoire")
        self._docs[doc.id] = doc
        return doc

    def get(self, doc_id: UUID) -> Document:
        doc = self._docs.get(doc_id)
        if doc is None:
            raise NotFoundError("document not found")
        return doc

    def list(self, *, etablissement_id: UUID | None = None) -> list[Document]:
        docs = list(self._docs.values())
        if etablissement_id is not None:
            docs = [d for d in docs if d.etablissement_id == etablissement_id]
        # tri stable: plus récent d'abord
        return sorted(docs, key=lambda d: d.uploaded_at, reverse=True)

    def validate(self, doc_id: UUID, *, user_id: UUID) -> Document:
        _ = user_id  # règle: action liée à un user
        doc = self.get(doc_id)
        doc2 = doc.validate()
        self._docs[doc_id] = doc2
        return doc2

    def delete(self, doc_id: UUID, *, user_id: UUID) -> None:
        _ = user_id  # règle: action liée à un user
        doc = self.get(doc_id)
        if doc.validated:
            raise ImmutableAfterValidationError("Suppression interdite: document validé")
        del self._docs[doc_id]
