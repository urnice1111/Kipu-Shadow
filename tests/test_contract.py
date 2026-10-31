import json
import threading

from app import pipeline
from app.config import OUTPUT_FILES
from app.ingestion.dirsource import DirSource
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


def test_run_publishes_anonymized_output(client, corpus_dir, settings, monkeypatch):
    seen = {}

    def fake_api(url, token):
        seen["args"] = (url, token)
        return DirSource(corpus_dir)

    monkeypatch.setattr(pipeline, "ApiSource", fake_api)
    r = client.post("/v1/run", json=RUN_BODY)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    body = wait_for(client, job_id, timeout=30)
    assert seen["args"] == (RUN_BODY["sources_url"], RUN_BODY["token"])
    assert body["status"] == "done", body
    assert body["records"] == {"chats": 5, "docs": 3, "tables": 4}
    assert RUN_BODY["token"] not in client.get(f"/v1/run/{job_id}").text
    published = "".join(client.get(f"/v1/output/{n}").text for n in ("chats.jsonl", "docs.jsonl", "tables.jsonl"))
    for real in ("Juan Pérez", "Laura Gómez", "Ana Ruiz", "juan_perez", "10101010", "ana@example.test"):
        assert real not in published
    assert "$250.000" in published
    ents = client.get("/v1/entities").json()["entities"]
    assert any(e["type"] == "person" and "Juan Pérez" in e["originals"] for e in ents)
    assert not settings.staging_dir.exists()


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
        assert "Juan Pérez" not in json.dumps(body["records"], ensure_ascii=False)


def test_anonymize_replaces_consistently_after_run(client, corpus_dir, monkeypatch):
    monkeypatch.setattr(pipeline, "ApiSource", lambda url, token: DirSource(corpus_dir))
    assert wait_for(client, client.post("/v1/run", json=RUN_BODY).json()["job_id"], timeout=30)["status"] == "done"
    published = [json.loads(l) for l in client.get("/v1/output/chats.jsonl").text.splitlines()]
    juan_pseudo = next(r["author"] for r in published if r["id"] == "m2")

    new = {**CHAT, "id": "live-1", "author": "Juan Pérez", "text": "Hola, soy Juan Pérez otra vez, sigo con el cobro de $250.000."}
    body = client.post("/v1/anonymize", json={"source": "chats", "records": [new]}).json()
    rec = body["records"][0]
    assert rec["author"] == juan_pseudo
    assert juan_pseudo in rec["text"] and "Juan Pérez" not in rec["text"]
    assert "$250.000" in rec["text"]
    person = next(e for e in body["entities"] if e["type"] == "person")
    assert person["records"] == ["live-1"]
    assert person["pseudonyms"]["name"] == juan_pseudo


def test_anonymize_new_person_gets_new_pseudonym(client):
    a = {**CHAT, "id": "x1", "author": "Rosalía Quintana", "text": "Soy Rosalía Quintana, nueva clienta."}
    b = {**CHAT, "id": "x2", "author": "Hernán Quintana", "text": "Soy Hernán Quintana."}
    body = client.post("/v1/anonymize", json={"source": "chats", "records": [a, b]}).json()
    authors = [r["author"] for r in body["records"]]
    assert authors[0] != authors[1]
    assert "Quintana" not in json.dumps(body["records"], ensure_ascii=False)


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
