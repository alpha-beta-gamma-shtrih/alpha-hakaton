"""Small, verified demo CSV files, copied once and never served as static assets."""

import csv
import hashlib
import io
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from credit_cabinet.api.errors import APIError
from credit_cabinet.schemas.seed import CompanySeed, FinancialSeed, Manifest

logger = logging.getLogger(__name__)
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
STORAGE_KEY = re.compile(r"[a-f0-9]{32}/[a-f0-9]{32}/[a-f0-9]{64}\.csv")


def unavailable():
    logger.warning("document.unavailable")
    return APIError(
        503, "DOCUMENT_UNAVAILABLE", "Демо-документ недоступен; проверьте поставку и хранилище"
    )


def read_small(path: Path) -> bytes:
    with path.open("rb") as file:
        content = file.read(MAX_DOCUMENT_BYTES + 1)
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("Invalid document size")
    return content


def csv_rows(content: bytes, model):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    if reader.fieldnames is None or (
        len(reader.fieldnames) != len(model.model_fields)
        or set(reader.fieldnames) != set(model.model_fields)
    ):
        raise ValueError("Unexpected CSV columns")
    return [
        model.model_validate({key: value or None for key, value in row.items()}) for row in reader
    ]


class DocumentStore:
    def __init__(self, settings):
        self.directory = settings.documents_dir
        self.dataset = settings.demo_dataset_dir

    def templates(self, inn: str):
        """Resolve the company from verified input; paths never come from an API body."""
        try:
            root = self.dataset.resolve()
            manifest = Manifest.model_validate_json(read_small(root / "manifest.json"))

            def read(name, checksum):
                path = (root / name).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("Path outside dataset")
                content = read_small(path)
                if hashlib.sha256(content).hexdigest() != checksum:
                    raise ValueError("Checksum mismatch")
                return content

            companies = csv_rows(
                read("companies.csv", manifest.files["companies.csv"]), CompanySeed
            )
            keys = [row.company_key for row in companies if row.inn == inn]
            if len(keys) != 1:
                raise ValueError("Unknown company")
            templates = [row for row in manifest.document_templates if row.company_key == keys[0]]
            if not templates or len({row.path for row in templates}) != len(templates):
                raise ValueError("Missing or duplicate templates")
            result = []
            for template in templates:
                if (
                    not re.fullmatch(r"documents/[A-Za-z0-9_-]+\.csv", template.path)
                    or manifest.files[template.path] != template.content_sha256
                ):
                    raise ValueError("Invalid template")
                content = read(template.path, template.content_sha256)
                rows = csv_rows(content, FinancialSeed)
                if (
                    not rows
                    or len({row.month for row in rows}) != len(rows)
                    or any(
                        row.company_key != keys[0]
                        or row.month not in manifest.financial_months
                        or row.source != "DEMO"
                        for row in rows
                    )
                ):
                    raise ValueError("Invalid financial document")
                result.append((template, content))
            return result
        except (OSError, ValueError, KeyError, TypeError, ValidationError, csv.Error):
            raise unavailable() from None

    def path(self, key: str) -> Path:
        if not STORAGE_KEY.fullmatch(key):
            raise ValueError("Invalid storage key")
        root = self.directory.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Path outside storage")
        return path

    def save(self, application_id, document_id, checksum: str, content: bytes) -> str:
        key = f"{application_id.hex}/{document_id.hex}/{checksum}.csv"
        try:
            if (
                not content
                or len(content) > MAX_DOCUMENT_BYTES
                or hashlib.sha256(content).hexdigest() != checksum
            ):
                raise ValueError("Invalid content")
            path = self.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Unique document IDs and exclusive creation prevent replacement. A rolled-back
            # transaction can leave an unreferenced file, never a downloadable DB record.
            with path.open("xb") as file:
                file.write(content)
        except (OSError, ValueError):
            raise unavailable() from None
        return key

    def read(self, document) -> bytes:
        try:
            content = read_small(self.path(document.storage_key))
            if (
                len(content) != document.size_bytes
                or hashlib.sha256(content).hexdigest() != document.content_sha256
            ):
                raise ValueError("Stored document changed")
            return content
        except (OSError, ValueError):
            raise unavailable() from None
