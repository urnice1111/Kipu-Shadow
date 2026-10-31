"""Mechanisms behind the hidden-test families: name variants, homonym tie-breakers, quasi-identifiers
and identifiers outside the obvious fields."""

import copy
import re

import pytest

from app.core.anonymize import anonymize_corpus, prepare_engine
from app.core.engine import Ctx
from app.core.registry import Registry
from app.ingestion import ingest
from app.ingestion.dirsource import DirSource


def client_row(clid: str, **cols) -> dict:
    base = {"cliente_id": clid, "nombre_completo": "", "num_doc": "", "ciudad": "", "barrio": "", "notas": ""}
    return {"id": f"clientes:{clid}", "table": "clientes", "columns": {**base, **cols}}


def chat(rid: str, thread: str, author: str, text: str) -> dict:
    return {"id": rid, "thread_id": thread, "author": author, "ts": "9.9", "text": text, "attachments": []}


@pytest.fixture
def corpus(corpus_dir):
    c = copy.deepcopy(ingest(DirSource(corpus_dir)))
    c.tables += [
        client_row(
            "CL-10", nombre_completo="Rosa Elena Pardo Gil", num_doc="52123456", fecha_nacimiento="1983-10-18",
            ciudad="Cali", barrio="Granada", ocupacion="arquitecta", notas="Arquitecta, cliente desde 2021.",
        ),
        client_row("CL-11", nombre_completo="Camila Arango Velásquez", num_doc="1022649507", ciudad="Bogotá"),
        client_row("CL-12", nombre_completo="Camila Arango Mejía", num_doc="1035372961", ciudad="Medellín"),
        client_row("CL-13", nombre_completo="Ana Ruiz Toro", num_doc="43111222", ciudad="Pasto", ocupacion="periodista"),
        client_row(
            "CL-14", nombre_completo="Hugo Lara Peña", num_doc="79111333", ciudad="Cali", fecha_vinculacion="2019-09-27",
            ocupacion="conductor de plataforma", notas="Chef del restaurante del barrio. Crédito al día, trabaja como conductor.",
        ),
        {
            "id": "pqrs:PQR-2026-0001", "table": "pqrs",
            "columns": {"radicado": "PQR-2026-0001", "cliente_id": "CL-99", "cedula": "98901449", "ciudad": "Cali",
                        "agente": "", "descripcion": "", "respuesta": ""},
        },
    ]
    c.chats += [
        chat("g1", "general:1.0", "Laura Gómez", "La auditora es Juan Marulanda, socia de la firma."),
        chat("g2", "general:1.0", "Ana Ruiz", "Mañana Laura corre el backfill."),
    ]
    return c


@pytest.fixture
def run(corpus, tmp_path):
    engine = prepare_engine(corpus, Registry(tmp_path / "reg" / "p.db"))
    outputs = anonymize_corpus(engine, corpus)
    return engine, {r["id"]: r for recs in outputs.values() for r in recs}


def pid(engine, clid: str) -> str:
    return engine.d.by_clid[clid]


def test_birth_date_in_prose_is_replaced_in_the_same_style(run):
    engine, _ = run
    out = engine.text("Mi fecha es 18 de octubre de 1983", Ctx("x").push(pid(engine, "CL-10")))
    assert "1983" not in out and "18 de octubre" not in out
    assert re.fullmatch(r"Mi fecha es \d{1,2} de [a-z]+ de \d{4}", out)


def test_initial_and_surname_and_handles(run):
    engine, _ = run
    juan = pid(engine, "CL-1")
    out = engine.text("Abono crédito - J. Pérez", Ctx("x").push(juan))
    assert "Pérez" not in out and re.search(r" - [A-Z]\. \w+", out)
    out = engine.text("Juan Pérez publica como @jperez", Ctx("x"))
    assert "@jperez" not in out and re.search(r"@[a-z]+", out)


def test_lowercase_given_name_in_context(run):
    engine, _ = run
    rosa = pid(engine, "CL-10")
    assert not re.search(r"\brosa\b", engine.text("mil gracias rosa", Ctx("x").push(rosa)))
    assert engine.text("una rosa roja", Ctx("x").push(rosa)) == "una rosa roja"


def test_homonym_resolved_by_cedula_suffix_and_repeated_name(run):
    engine, _ = run
    a, b = pid(engine, "CL-11"), pid(engine, "CL-12")
    out = engine.text("Hola Camila! Me aparece Camila Arango, cédula terminada en 2961.", Ctx("x").push(a))
    assert engine.render_name(b, "all", "first") in out
    assert out.startswith("Hola " + engine.name_parts(a)["given"][0])
    out = engine.text("La PQR de Camila Arango con el extracto de Camila Arango: son dos clientas.", Ctx("x"))
    assert engine.render_name(a, "all", "first") in out and engine.render_name(b, "all", "first") in out


def test_role_cue_picks_agent_or_client(run):
    engine, _ = run
    agent, client = engine.d.by_kp["KP-1"], pid(engine, "CL-13")
    ctx = Ctx("x").push(client)
    out = engine.text("Te atiende Ana Ruiz, agente de soporte.", ctx)
    assert engine.render_name(agent, "all", "all") in out
    out = engine.text("Hola Ana Ruiz, te saluda Laura de cobros.", Ctx("x").push(client))
    assert engine.render_name(client, "all", "first") in out


def test_occupation_in_notes_and_capitalized_sentence(run):
    _, out = run
    notes = out["clientes:CL-10"]["columns"]["notas"]
    assert "Arquitecta" not in notes and "hace unos años" in notes and notes.startswith("Profesional de la construcción")
    assert out["clientes:CL-10"]["columns"]["ocupacion"] == "profesional de la construcción"


def test_occupations_in_own_notes_without_punctuation_and_head_word(run):
    _, out = run
    notes = out["clientes:CL-14"]["columns"]["notas"]
    assert "Chef" not in notes and "conductor" not in notes
    assert notes.startswith("Profesional de gastronomía del restaurante") and "trabaja como profesional del transporte" in notes


def test_homonym_resolved_by_occupation_next_to_name(run):
    engine, _ = run
    agent, client = engine.d.by_kp["KP-1"], pid(engine, "CL-13")
    out = engine.text("Trabajaremos con Ana Ruiz. Es periodista independiente.", Ctx("x", prefer="employee"))
    assert engine.render_name(client, "all", "first") in out
    assert engine.render_name(agent, "all", "all") not in out


def test_third_party_next_to_known_given_name_and_internal_first_name(run):
    engine, out = run
    assert "Marulanda" not in out["g1"]["text"]
    laura = engine.d.by_kp["KP-2"]
    assert out["g2"]["text"] == f"Mañana {engine.name_parts(laura)['given'][0]} corre el backfill."


def test_pqrs_cedula_without_known_owner(run):
    _, out = run
    ced = out["pqrs:PQR-2026-0001"]["columns"]["cedula"]
    assert ced != "98901449" and re.fullmatch(r"\d{8}", ced)
