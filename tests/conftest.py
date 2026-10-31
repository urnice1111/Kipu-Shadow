import json
import time
from pathlib import Path

import pymupdf
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


USERS = [
    {"id": "UBOT", "name": "kipi", "real_name": "Kipi", "is_bot": True, "profile": {"real_name": "Kipi"}},
    {"id": "U1", "name": "jperez", "real_name": "Juan Pérez", "is_bot": False, "profile": {"title": "Cliente"}},
    {
        "id": "U2",
        "name": "laura.gomez",
        "real_name": "",
        "is_bot": False,
        "profile": {"real_name": "Laura Gómez", "email": "laura.gomez@example.test", "title": "Agente"},
    },
    {"id": "U3", "name": "deactivateduser", "real_name": "", "deleted": True, "profile": {"real_name": ""}},
]

MESSAGES = {
    "2026-01-01": [
        {"type": "message", "user": "UBOT", "subtype": "bot_message", "username": "Kipi",
         "text": "Hola, soy Kipi.", "ts": "1000.000100", "client_msg_id": "m1"},
        {"type": "message", "user": "U1", "text": "Hola <@U2>, me cobraron doble $250.000",
         "ts": "1000.000200", "thread_ts": "1000.000100", "client_msg_id": "m2",
         "reactions": [{"name": "eyes", "users": ["U2"], "count": 1}]},
        {"type": "message", "user": "U2", "text": "Te adjunto el extracto",
         "ts": "1000.000300", "thread_ts": "1000.000100", "client_msg_id": "m3",
         "files": [{"id": "F1", "name": "extracto_juan_perez.pdf", "title": "extracto"}],
         "edited": {"user": "U2", "ts": "1000.000400"}},
    ],
    "2026-01-02": [
        {"type": "message", "user": "U3", "text": "hola", "ts": "2000.000100", "client_msg_id": "m4"},
        {"type": "message", "user": "U1", "text": "<@U9> sigo esperando", "ts": "2000.000200",
         "thread_ts": "1000.000100", "client_msg_id": "m5"},
    ],
}

MD = """---
title: "Memo de prueba"
author: ana@example.test
asistentes:
  - Ana Ruiz
  - Pedro Gil
tags: [uno, dos]
---
# Memo de prueba

Preparado por Ana Ruiz.
"""

HTML = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<title>Organigrama</title>
<meta name="author" content="Ana Ruiz">
<meta name="description" content="Estructura">
<style>body{color:red}</style>
</head><body>
<!-- revisado por Pedro Gil -->
<h1>Organigrama</h1>
<p>Cada persona <b>reporta</b> a otra.<br>Segunda línea.</p>
<ul><li>Uno</li><li>Dos</li></ul>
<table><tr><th>Cargo</th><th>Persona</th></tr>
<tr><td>CEO</td><td>Ana Ruiz (<a href="mailto:ana@example.test">ana@example.test</a>)</td></tr></table>
</body></html>
"""

CLIENTES = (
    "cliente_id;nombre_completo;num_doc;ciudad;notas\r\n"
    "CL-1;Juan Pérez;10101010;Bogotá;cliente desde 2020\r\n"
    "CL-2;María Gómez;20202020;Cali;\r\n"
)

EMPLEADOS = """<?xml version="1.0" encoding="UTF-8"?>
<empleados corte="2026-01-01">
  <!-- comentario -->
  <empleado id="KP-1" cargo="CEO" reporta_a="">
    <nombre>Ana Ruiz</nombre>
    <documento tipo="CC">41111111</documento>
  </empleado>
  <empleado id="KP-2" cargo="Agente" reporta_a="Ana Ruiz">
    <nombre>Laura Gómez</nombre>
    <documento tipo="CE">52222222</documento>
  </empleado>
</empleados>
"""


def make_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Carta de cobro")
    page.insert_text((72, 100), "Señor Juan Pérez, cédula 10101010.")
    doc.set_metadata({"title": "Carta de cobro", "author": "Ana Ruiz", "keywords": "cobro"})
    data = doc.tobytes()
    doc.close()
    return data


def write_corpus_dir(root: Path) -> Path:
    """Synthetic corpus with sample.zip's input/ layout plus record_index.json next to it."""
    inp = root / "input"
    (inp / "chats" / "soporte").mkdir(parents=True)
    (inp / "docs").mkdir()
    (inp / "tables").mkdir()
    (inp / "chats" / "channels.json").write_text(
        json.dumps([{"id": "C1", "name": "soporte", "members": ["U1", "U2"]}]), "utf-8"
    )
    (inp / "chats" / "users.json").write_text(json.dumps(USERS, ensure_ascii=False), "utf-8")
    for date, msgs in MESSAGES.items():
        (inp / "chats" / "soporte" / f"{date}.json").write_text(json.dumps(msgs, ensure_ascii=False), "utf-8")
    (inp / "docs" / "index.json").write_text(
        json.dumps(
            [
                {"id": "d_md", "filename": "memo.md", "format": "md"},
                {"id": "d_html", "filename": "organigrama.html", "format": "html"},
                {"id": "d_pdf", "filename": "carta_juan_perez.pdf", "format": "pdf"},
            ]
        ),
        "utf-8",
    )
    (inp / "docs" / "memo.md").write_text(MD, "utf-8")
    (inp / "docs" / "organigrama.html").write_text(HTML, "utf-8")
    (inp / "docs" / "carta_juan_perez.pdf").write_bytes(make_pdf())
    (inp / "tables" / "clientes.csv").write_bytes(CLIENTES.encode("latin-1"))
    (inp / "tables" / "empleados.xml").write_text(EMPLEADOS, "utf-8")
    (root / "record_index.json").write_text(
        json.dumps(
            {
                "chats": ["m1", "m2", "m3", "m4", "m5"],
                "docs": ["d_md", "d_html", "d_pdf"],
                "tables": ["clientes:CL-1", "clientes:CL-2", "empleados:KP-1", "empleados:KP-2"],
            }
        ),
        "utf-8",
    )
    return inp


@pytest.fixture
def corpus_dir(tmp_path) -> Path:
    return write_corpus_dir(tmp_path / "corpus")
