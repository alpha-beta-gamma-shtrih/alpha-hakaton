import hashlib
import json
from shutil import copytree
from types import SimpleNamespace
from uuid import uuid4

import pytest

from credit_cabinet.api.errors import APIError
from credit_cabinet.integrations.documents import MAX_DOCUMENT_BYTES, DocumentStore
from tests.conftest import ROOT


@pytest.fixture
def store(settings, tmp_path):
    dataset = copytree(ROOT / "demo_data/demo_0_2", tmp_path / "dataset")
    return DocumentStore(settings.model_copy(update={"demo_dataset_dir": dataset}))


def persisted(store):
    template, content = store.templates("0000000001")[0]
    document = SimpleNamespace(
        content_sha256=template.content_sha256,
        size_bytes=len(content),
        storage_key=store.save(uuid4(), uuid4(), template.content_sha256, content),
    )
    return document, content


def test_private_copy_survives_dataset_change_and_restart(store):
    document, content = persisted(store)
    (store.dataset / "documents/C01.csv").write_bytes(b"changed template")
    restarted = DocumentStore(
        SimpleNamespace(documents_dir=store.directory, demo_dataset_dir=store.dataset)
    )
    assert restarted.read(document) == content


@pytest.mark.parametrize("failure", ["missing", "hash", "large", "unknown", "traversal"])
def test_invalid_template_fails_closed(store, failure):
    path = store.dataset / "documents/C01.csv"
    if failure == "missing":
        path.unlink()
    elif failure == "hash":
        path.write_bytes(b"corrupt")
    elif failure == "large":
        path.write_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1))
    elif failure == "traversal":
        manifest_path = store.dataset / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["document_templates"][0]["path"] = "../secret.csv"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(APIError) as error:
        store.templates("0000000000" if failure == "unknown" else "0000000001")
    assert error.value.status_code == 503
    assert error.value.code == "DOCUMENT_UNAVAILABLE"
    assert str(store.dataset) not in error.value.message


@pytest.mark.parametrize("failure", ["missing", "hash", "size", "traversal", "absolute"])
def test_stored_files_verified_before_read(store, failure):
    document, content = persisted(store)
    path = store.path(document.storage_key)
    if failure == "missing":
        path.unlink()
    elif failure == "hash":
        path.write_bytes(b"x" * len(content))
    elif failure == "size":
        document.size_bytes += 1
    else:
        document.storage_key = "../secret.csv" if failure == "traversal" else str(path)
    with pytest.raises(APIError) as error:
        store.read(document)
    assert error.value.code == "DOCUMENT_UNAVAILABLE"


def test_save_never_overwrites_file(store):
    document, content = persisted(store)
    app, doc, _ = document.storage_key.split("/")
    from uuid import UUID

    with pytest.raises(APIError):
        store.save(UUID(app), UUID(doc), hashlib.sha256(content).hexdigest(), content)
    assert store.read(document) == content
