import dataclasses
import json

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import wait_for
from tests.test_contract import CHAT, RUN_BODY, fake_pipeline


def read_log(log_dir):
    return [json.loads(line) for line in (log_dir / "requests.jsonl").read_text("utf-8").splitlines()]


def test_every_request_is_logged_with_bodies(settings, tmp_path):
    log_dir = tmp_path / "logs"
    client = TestClient(create_app(dataclasses.replace(settings, log_dir=log_dir), fake_pipeline))

    client.get("/v1/health")
    job_id = client.post("/v1/run", json=RUN_BODY).json()["job_id"]
    wait_for(client, job_id)
    client.get("/v1/output/chats.jsonl")
    anon = client.post("/v1/anonymize", json={"source": "chats", "records": [CHAT]}).json()
    client.post("/v1/anonymize", json={"source": "emails", "records": [CHAT]})

    entries = read_log(log_dir)
    by_path = {}
    for e in entries:
        by_path.setdefault((e["method"], e["path"]), []).append(e)

    assert by_path[("GET", "/v1/health")][0]["response"]["status"] == "ok"

    run = by_path[("POST", "/v1/run")][0]
    assert run["status"] == 202
    assert run["request"] == {"sources_url": RUN_BODY["sources_url"], "token": "***"}
    assert RUN_BODY["token"] not in (log_dir / "requests.jsonl").read_text("utf-8")

    download = by_path[("GET", "/v1/output/chats.jsonl")][0]
    assert download["status"] == 200
    assert download["response"]["bytes"] > 0 and len(download["response"]["sha256"]) == 64

    ok, bad = by_path[("POST", "/v1/anonymize")]
    assert ok["request"]["records"] == [CHAT]
    assert ok["response"] == anon
    assert bad["status"] == 422
    assert bad["response"]["detail"]

    runs = list((log_dir / "runs").iterdir())
    assert len(runs) == 1 and runs[0].name.endswith(job_id)
    assert (runs[0] / "chats.jsonl").is_file()
