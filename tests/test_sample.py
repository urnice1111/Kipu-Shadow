"""Compare our ingestion of sample/ with its ideal output on structure only
(the ideal output's text is already anonymized)."""

import json
from itertools import combinations
from pathlib import Path

import pytest

from app.ingestion import check_ids, ingest
from app.ingestion.dirsource import DirSource

SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "unpacked"

pytestmark = pytest.mark.skipif(
    not (SAMPLE / "input").is_dir(), reason="sample/ no está descargado (scripts/fetch_sample.sh)"
)


def load(name):
    return {
        r["id"]: r
        for r in map(json.loads, (SAMPLE / "expected_output" / name).read_text("utf-8").splitlines())
        if r
    }


@pytest.fixture(scope="module")
def corpus():
    corpus = ingest(DirSource(SAMPLE / "input"))
    check_ids(corpus)
    return corpus


def test_chats_match_structure(corpus):
    expected = load("chats.jsonl")
    ours = {r["id"]: r for r in corpus.chats}
    assert ours.keys() == expected.keys()
    for rid, exp in expected.items():
        assert ours[rid]["thread_id"] == exp["thread_id"]
        assert ours[rid]["ts"] == exp["ts"]
        assert len(ours[rid]["attachments"]) == len(exp["attachments"])
        assert set(ours[rid]) == set(exp)
    for a, b in combinations(expected, 2):
        assert (ours[a]["author"] == ours[b]["author"]) == (expected[a]["author"] == expected[b]["author"])
    assert ours["012ca87b-3c25-511d-b57f-28b9a4f9dc4d"]["author"] == "Kipi"


def test_docs_match_structure(corpus):
    expected = load("docs.jsonl")
    ours = {r["id"]: r for r in corpus.docs}
    assert ours.keys() == expected.keys()
    for rid, exp in expected.items():
        assert ours[rid]["format"] == exp["format"]
        assert ours[rid]["filename"] == exp["filename"]
        assert list(ours[rid]["metadata"]) == list(exp["metadata"])
        assert ours[rid]["metadata"]["fecha"] == exp["metadata"]["fecha"]


def test_tables_match_structure(corpus):
    expected = load("tables.jsonl")
    ours = {r["id"]: r for r in corpus.tables}
    assert ours.keys() == expected.keys()
    for rid, exp in expected.items():
        assert ours[rid]["table"] == exp["table"]
        assert list(ours[rid]["columns"]) == list(exp["columns"])
        assert ours[rid]["columns"]["cliente_id"] == exp["columns"]["cliente_id"]
        assert ours[rid]["columns"]["fecha_vinculacion"] == exp["columns"]["fecha_vinculacion"]
