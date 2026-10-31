import pytest

from app.ingestion import IngestError, check_ids, ingest
from app.ingestion.dirsource import DirSource
from app.ingestion.docs import html_to_markdown, parse_front_matter
from app.ingestion.tables import parse_csv, parse_xml
from tests.conftest import CLIENTES, MD


@pytest.fixture
def corpus(corpus_dir):
    corpus = ingest(DirSource(corpus_dir))
    check_ids(corpus)
    return corpus


def by_id(records):
    return {r["id"]: r for r in records}


def test_chat_threads_authors_and_attachments(corpus):
    chats = by_id(corpus.chats)
    assert [r["id"] for r in corpus.chats] == ["m1", "m2", "m3", "m4", "m5"]
    for mid in ("m1", "m2", "m3", "m5"):
        assert chats[mid]["thread_id"] == "soporte:1000.000100"
    assert chats["m4"]["thread_id"] == "soporte:2000.000100"
    assert chats["m1"]["author"] == "Kipi"
    assert chats["m2"]["author"] == "Juan Pérez"
    assert chats["m3"]["author"] == "Laura Gómez"
    assert chats["m4"]["author"] == "deactivateduser"
    assert chats["m3"]["attachments"] == [{"filename": "extracto_juan_perez.pdf"}]
    assert chats["m1"]["attachments"] == []
    assert set(chats["m2"]) == {"id", "thread_id", "author", "ts", "text", "attachments"}


def test_mentions_resolved_to_names(corpus):
    chats = by_id(corpus.chats)
    assert chats["m2"]["text"] == "Hola @Laura Gómez, me cobraron doble $250.000"
    assert chats["m5"]["text"] == "<@U9> sigo esperando"


def test_markdown_doc(corpus):
    doc = by_id(corpus.docs)["d_md"]
    assert doc["body"] == MD
    assert doc["title"] == "Memo de prueba"
    assert doc["metadata"] == {
        "title": "Memo de prueba",
        "author": "ana@example.test",
        "asistentes": "Ana Ruiz, Pedro Gil",
        "tags": "uno, dos",
    }


def test_html_doc(corpus):
    doc = by_id(corpus.docs)["d_html"]
    assert doc["title"] == "Organigrama"
    assert doc["metadata"] == {"author": "Ana Ruiz", "description": "Estructura"}
    body = doc["body"]
    assert "<!-- revisado por Pedro Gil -->" in body
    assert "# Organigrama" in body
    assert "Cada persona reporta a otra.\nSegunda línea." in body
    assert "- Uno\n- Dos" in body
    assert "| Cargo | Persona |\n| --- | --- |\n| CEO | Ana Ruiz (ana@example.test) |" in body
    assert "color:red" not in body


def test_pdf_doc(corpus):
    doc = by_id(corpus.docs)["d_pdf"]
    assert doc["format"] == "pdf"
    assert doc["filename"] == "carta_juan_perez.pdf"
    assert doc["title"] == "Carta de cobro"
    assert doc["metadata"]["author"] == "Ana Ruiz"
    assert doc["metadata"]["keywords"] == "cobro"
    assert "Señor Juan Pérez, cédula 1010." in doc["body"]
    assert all(isinstance(v, str) and v for v in doc["metadata"].values())


def test_tables(corpus):
    tables = by_id(corpus.tables)
    row = tables["clientes:CL-1"]
    assert row["table"] == "clientes"
    assert row["columns"] == {
        "cliente_id": "CL-1",
        "nombre_completo": "Juan Pérez",
        "num_doc": "1010",
        "ciudad": "Bogotá",
        "notas": "cliente desde 2020",
    }
    assert tables["clientes:CL-2"]["columns"]["notas"] == ""
    emp = tables["empleados:KP-2"]["columns"]
    assert emp == {
        "id": "KP-2",
        "cargo": "Agente",
        "reporta_a": "Ana Ruiz",
        "nombre": "Laura Gómez",
        "documento": "222",
        "documento_tipo": "CE",
    }
    assert all(isinstance(v, str) for r in corpus.tables for v in r["columns"].values())


def test_csv_latin1_and_extra_column():
    rows = parse_csv(CLIENTES.encode("latin-1"), "latin-1", ";")
    assert rows[0]["nombre_completo"] == "Juan Pérez"
    with pytest.raises(ValueError):
        parse_csv(b"a,b\r\n1,2,3\r\n", "utf-8", ",")


def test_xml_skips_comments():
    rows = parse_xml(b"<r><!-- x --><f id='1'><n>A</n></f></r>")
    assert rows == [{"id": "1", "n": "A"}]


def test_front_matter_absent():
    assert parse_front_matter("# Sin front matter\n") == {}


def test_html_inline_comment_kept():
    md = html_to_markdown("<p>Hola <!-- nota --> mundo</p>")
    assert md == "Hola <!-- nota --> mundo\n"


def test_check_ids_reports_missing_extra_and_duplicates(corpus):
    corpus.chats.append(dict(corpus.chats[0]))
    corpus.chats.append({**corpus.chats[0], "id": "intruso"})
    corpus.docs = corpus.docs[1:]
    with pytest.raises(IngestError) as err:
        check_ids(corpus)
    message = str(err.value)
    assert "chats: 1 ids repetidos" in message
    assert "chats: sobran 1" in message
    assert "docs: faltan 1" in message
