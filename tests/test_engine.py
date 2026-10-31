import copy
import json
import re
import time

import pytest

from app.core.anonymize import anonymize_corpus, prepare_engine
from app.core.audit import audit
from app.core.engine import Ctx
from app.core.entities import build_entities
from app.core.registry import Registry
from app.ingestion import ingest
from app.ingestion.dirsource import DirSource


@pytest.fixture
def corpus(corpus_dir):
    return ingest(DirSource(corpus_dir))


@pytest.fixture
def registry(tmp_path):
    return Registry(tmp_path / "reg" / "pseudonyms.db")


def run(corpus, registry):
    engine = prepare_engine(corpus, registry)
    outputs = anonymize_corpus(engine, corpus)
    return engine, outputs, build_entities(engine)


def name_of(entities, original):
    return next(e["pseudonyms"]["name"] for e in entities if original in e.get("originals", []))


def test_corpus_has_no_leaks_and_keeps_business_data(corpus, registry):
    engine, outputs, entities = run(corpus, registry)
    report = audit(outputs, entities)
    assert report.ok, (report.leaks, report.unused_pseudonyms)
    text = json.dumps(outputs, ensure_ascii=False)
    assert "$250.000" in text
    assert "cliente desde 2020" in text
    rows = {r["id"]: r["columns"] for r in outputs["tables"]}
    assert rows["clientes:CL-1"]["cliente_id"] == "CL-1"
    assert rows["empleados:KP-2"]["reporta_a"] == name_of(entities, "Ana Ruiz")


def test_same_person_same_pseudonym_everywhere(corpus, registry):
    engine, outputs, entities = run(corpus, registry)
    juan = name_of(entities, "Juan Pérez")
    chats = {r["id"]: r for r in outputs["chats"]}
    assert chats["m2"]["author"] == juan
    assert juan in json.dumps(outputs["tables"], ensure_ascii=False)
    assert "juan_perez" not in chats["m3"]["attachments"][0]["filename"]


def test_pseudonyms_survive_restart_and_growth(corpus, registry, tmp_path):
    _, _, before = run(corpus, registry)
    registry.close()

    grown = copy.deepcopy(corpus)
    grown.tables.append(
        {"id": "clientes:CL-3", "table": "clientes",
         "columns": {"cliente_id": "CL-3", "nombre_completo": "Juan Pérez Rojas", "num_doc": "30303030", "ciudad": "Pasto", "notas": ""}}
    )
    reopened = Registry(tmp_path / "reg" / "pseudonyms.db")
    _, _, after = run(grown, reopened)
    old = {e["entity_id"]: e["pseudonyms"] for e in before if e["type"] == "person"}
    new = {e["entity_id"]: e["pseudonyms"] for e in after if e["type"] == "person"}
    for eid, pseudos in old.items():
        for kind, value in pseudos.items():
            assert new[eid][kind] == value
    added = [p for eid, p in new.items() if eid not in old]
    assert len(added) == 1
    assert added[0]["name"] not in {p["name"] for p in old.values()}


def test_spelled_email_uppercase_and_kept_terms(corpus, registry):
    engine, _, _ = run(corpus, registry)
    ctx = Ctx("x")
    out = engine.text("Escríbanle a ana punto ruiz arroba example punto test o a ANA RUIZ por Bancolombia.", ctx)
    assert "ana punto ruiz" not in out and "ANA RUIZ" not in out
    assert " arroba " in out and " punto " in out
    assert "Bancolombia" in out
    upper = out.split(" o a ")[1].split(" por ")[0]
    assert upper == upper.upper()


def test_amounts_dates_and_ids_untouched(corpus, registry):
    engine, _, _ = run(corpus, registry)
    text = "Pago de 1.350.000 el 2026-09-14 para CL-1, radicado PQR-2026-0451, crédito por 418.600."
    assert engine.text(text, Ctx("x")) == text


def test_plate_in_filename_and_unknown_phone(corpus, registry):
    engine, _, _ = run(corpus, registry)
    out = engine.text("SOAT_LTE758_2026.pdf y mi celular es 315 222 3344", Ctx("x"))
    assert "LTE758" not in out and "315 222 3344" not in out
    assert re.fullmatch(r"SOAT_[A-Z]{3}\d{3}_2026\.pdf y mi celular es 3\d\d \d{3} \d{4}", out)


def test_migrated_client_row_merges_and_bare_cedula_is_replaced(corpus, registry):
    grown = copy.deepcopy(corpus)
    grown.tables.append(
        {
            "id": "clientes:PG-1",
            "table": "clientes",
            "columns": {
                "cliente_id": "PG-1",
                "nombre_completo": "Juan Pérez",
                "num_doc": "10101010",
                "ciudad": "Bogotá",
                "notas": "migrado",
            },
        }
    )
    grown.chats.append(
        {
            "id": "m-ced",
            "thread_id": "soporte:9.9",
            "author": "Juan Pérez",
            "ts": "9.9",
            "text": "10.101.010",
            "attachments": [],
        }
    )
    engine, outputs, entities = run(grown, registry)
    assert engine.d.by_clid["CL-1"] == engine.d.by_clid["PG-1"]
    assert "10101010" not in engine.d.ambiguous_cedulas
    chats = {r["id"]: r for r in outputs["chats"]}
    assert "10101010" not in chats["m-ced"]["text"]
    rows = {r["id"]: r["columns"] for r in outputs["tables"]}
    assert rows["clientes:CL-1"]["cliente_id"] == "CL-1"
    assert rows["clientes:PG-1"]["cliente_id"] == "PG-1"
    assert rows["clientes:CL-1"]["num_doc"] == rows["clientes:PG-1"]["num_doc"]
    report = audit(outputs, entities)
    assert not any(leak["original"] == "10101010" for leak in report.leaks), report.leaks


def test_live_batch_of_fifty_under_a_minute(make_client, corpus_dir, monkeypatch):
    from app import pipeline
    from tests.conftest import wait_for

    client = make_client()
    monkeypatch.setattr(pipeline, "ApiSource", lambda url, token: DirSource(corpus_dir))
    assert wait_for(client, client.post("/v1/run", json={"sources_url": "x", "token": "t"}).json()["job_id"], 30)["status"] == "done"
    records = [
        {"id": f"live-{i}", "thread_id": "soporte:9.1", "author": "Juan Pérez", "ts": f"9.{i}",
         "text": f"Soy Juan Pérez, cédula 10101010, escribo a ana@example.test por {i}", "attachments": []}
        for i in range(50)
    ]
    start = time.monotonic()
    body = client.post("/v1/anonymize", json={"source": "chats", "records": records}).json()
    assert time.monotonic() - start < 60
    authors = {r["author"] for r in body["records"]}
    assert len(authors) == 1 and "Juan Pérez" not in authors
    assert "10101010" not in json.dumps(body["records"])
