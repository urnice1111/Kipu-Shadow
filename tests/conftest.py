import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        staging_dir=tmp_path / "output_staging",
    )


@pytest.fixture
def make_client(settings):
    def make(pipeline=None) -> TestClient:
        return TestClient(create_app(settings, pipeline))

    return make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def wait_for(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/v1/run/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} no terminó en {timeout}s")
