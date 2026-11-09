"""Shared fixtures: an isolated DEMO_MODE app on a temporary SQLite database."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from intakeagent.config import Settings
from intakeagent.main import create_app
from intakeagent.stt.stub import SCRIPTS


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        DEMO_MODE=True,
        DATABASE_URL=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        FHIR_PUSH=False,
        CLIO_ACCESS_TOKEN="",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def healthcare_transcript() -> str:
    return " ".join(SCRIPTS["healthcare"])


@pytest.fixture
def legal_transcript() -> str:
    return " ".join(SCRIPTS["legal"])
