import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

_SCRUB = [
    "HARNESS_INFERENCE_API_KEY", "OPENAI_API_KEY", "BOX_JWT_CONFIG_JSON", "BOX_MOUNT_BINARY_URL",
    "BOX_FOLDER_ID", "BOX_SHARED_LINK_ACCESS", "SUMMARY_FILENAME", "MAX_FILES", "BOX_MOUNT_SHA256", "BOX_ALLOW_API_FALLBACK",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _SCRUB:
        monkeypatch.delenv(k, raising=False)
    from box_doc_summarizer import box_api

    box_api.set_box_client_factory(None)
    yield
    box_api.set_box_client_factory(None)
