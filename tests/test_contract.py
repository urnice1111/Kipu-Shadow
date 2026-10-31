import json
import threading

from app.config import OUTPUT_FILES
from app.pipeline import RunResult
from tests.conftest import wait_for

RUN_BODY = {"sources_url": "https://fuentes.example.test/v1", "token": "tok-secreto-123"}

CHAT = {
    "id": "demo-msg-1",
    "thread_id": "soporte:1000.0001",
    "author": "Juan Pérez",
    "ts": "1000.0001",
    "text": "Soy Juan Pérez, tengo un cobro duplicado de $250.000.",
    "attachments": [{"filename": "extracto.pdf"}],
}
DOC = {
    "id": "doc_demo",
    "format": "md",
    "filename": "memo.md",
    "title": "Memo",
    "body": "---\nauthor: alguien@example.test\n---\n# Memo",
    "metadata": {"author": "alguien@example.test", "fecha": "2026-08-01"},
}
ROW = {
    "id": "clientes:CL-00001",
    "table": "clientes",
    "columns": {"cliente_id": "CL-00001", "nombre_completo": "Juan Pérez", "notas": ""},
}


def fake_pipeline(sources_url, token, staging):
    (staging / "chats.jsonl").write_text(json.dumps(CHAT, ensure_ascii=False) + "\n", "utf-8")
    (staging / "docs.jsonl").write_text(json.dumps(DOC, ensure_ascii=False) + "\n", "utf-8")
    (staging / "tables.jsonl").write_text(json.dumps(ROW, ensure_ascii=False) + "\n", "utf-8")
    (staging / "entities.json").write_text(json.dumps({"entities": []}), "utf-8")
    return RunResult(records={"chats": 1, "docs": 1, "tables": 1})


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "team": "Kipu Shadow", "version": "0.1.0", "models": []}


def test_run_stub_fails_honestly_without_leaking_token(client):
    r = client.post("/v1/run", json=RUN_BODY)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    body = wait_for(client, job_id)
    assert body["status"] == "failed"
    assert "no implementado" in body["error"]
    assert body["started_at"] and body["finished_at"]
    assert set(body["records"]) == {"chats", "docs", "tables"}
    assert set(body["cost"]) == {"tokens_in", "tokens_out", "seconds"}
    assert RUN_BODY["token"] not in client.get(f"/v1/run/{job_id}").text
    assert client.get("/v1/output/chats.jsonl").status_code == 404


def test_run_error_redacts_token(make_client):
    def leaky(sources_url, token, staging):
        raise RuntimeError(f"fallo con Bearer {token}")

    client = make_client(leaky)
    job_id = client.post("/v1/run", json=RUN_BODY).json()["job_id"]
    body = wait_for(client, job_id)
    assert body["status"] == "failed"
    assert RUN_BODY["token"] not in body["error"]
    assert "***" in body["error"]


def test_run_is_idempotent_while_active(make_client):
    release = threading.Event()

    def slow(sources_url, token, staging):
        release.wait(5)
        return fake_pipeline(sources_url, token, staging)

    client = make_client(slow)
    first = client.post("/v1/run", json=RUN_BODY).json()["job_id"]
    second = client.post("/v1/run", json=RUN_BODY).json()["job_id"]
    assert first == second
    release.set()
    assert wait_for(client, first)["status"] == "done"
    assert client.post("/v1/run", json=RUN_BODY).json()["job_id"] != first


def test_run_requires_body(client):
    assert client.post("/v1/run", json={"sources_url": "x"}).status_code == 422


def test_unknown_job_is_404(client):
    assert client.get("/v1/run/no-existe").status_code == 404


def test_output_and_entities_404_before_done(client):
    for name in OUTPUT_FILES:
        assert client.get(f"/v1/output/{name}").status_code == 404
    assert client.get("/v1/entities").status_code == 404


def test_output_rejects_other_names(make_client, settings):
    client = make_client(fake_pipeline)
    wait_for(client, client.post("/v1/run", json=RUN_BODY).json()["job_id"])
    for name in ("secret.txt", "..%2Fdata%2Fregistry.db", "../data/registry.db", "chats.jsonl.bak"):
        assert client.get(f"/v1/output/{name}").status_code == 404


def test_done_run_publishes_four_files(make_client, settings):
    client = make_client(fake_pipeline)
    job_id = client.post("/v1/run", json=RUN_BODY).json()["job_id"]
    body = wait_for(client, job_id)
    assert body["status"] == "done"
    assert body["records"] == {"chats": 1, "docs": 1, "tables": 1}
    assert "error" not in body
    assert sorted(p.name for p in settings.output_dir.iterdir()) == sorted(OUTPUT_FILES)
    assert not settings.staging_dir.exists()

    r = client.get("/v1/output/chats.jsonl")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert json.loads(r.text.splitlines()[0])["id"] == CHAT["id"]

    r = client.get("/v1/output/entities.json")
    assert r.headers["content-type"].startswith("application/json")
    assert client.get("/v1/entities").json() == {"entities": []}


def test_failed_run_keeps_previous_output(make_client, settings):
    calls = {"n": 0}

    def first_ok_then_fail(sources_url, token, staging):
        calls["n"] += 1
        if calls["n"] == 1:
            return fake_pipeline(sources_url, token, staging)
        (staging / "chats.jsonl").write_text("parcial\n")
        raise RuntimeError("fuente caída")

    client = make_client(first_ok_then_fail)
    wait_for(client, client.post("/v1/run", json=RUN_BODY).json()["job_id"])
    second = client.post("/v1/run", json=RUN_BODY).json()["job_id"]
    assert wait_for(client, second)["status"] == "failed"
    r = client.get("/v1/output/chats.jsonl")
    assert r.status_code == 200
    assert json.loads(r.text.splitlines()[0])["id"] == CHAT["id"]


def test_anonymize_keeps_ids_and_order_per_source(client):
    for source, record in (("chats", CHAT), ("docs", DOC), ("tables", ROW)):
        records = [{**record, "id": f"{record['id']}-{i}"} for i in range(3)]
        r = client.post("/v1/anonymize", json={"source": source, "records": records})
        assert r.status_code == 200, r.text
        body = r.json()
        assert [x["id"] for x in body["records"]] == [x["id"] for x in records]
        assert body["entities"] == []


def test_anonymize_accepts_fifty_rejects_fiftyone(client):
    records = [{**CHAT, "id": f"m{i}"} for i in range(51)]
    assert client.post("/v1/anonymize", json={"source": "chats", "records": records[:50]}).status_code == 200
    assert client.post("/v1/anonymize", json={"source": "chats", "records": records}).status_code == 422


def test_anonymize_schema_errors(client):
    missing = {k: v for k, v in CHAT.items() if k != "thread_id"}
    assert client.post("/v1/anonymize", json={"source": "chats", "records": [missing]}).status_code == 422
    assert client.post("/v1/anonymize", json={"source": "docs", "records": [CHAT]}).status_code == 422
    assert client.post("/v1/anonymize", json={"source": "emails", "records": [CHAT]}).status_code == 422
    bad_cols = {**ROW, "columns": {"cliente_id": 1}}
    assert client.post("/v1/anonymize", json={"source": "tables", "records": [bad_cols]}).status_code == 422
