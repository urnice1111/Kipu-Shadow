"""Pydantic models taken from api/participante.openapi.yaml."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["chats", "docs", "tables"]
JobStatus = Literal["queued", "running", "done", "failed"]


class _Record(BaseModel):
    # Unknown fields are kept and echoed back rather than dropped.
    model_config = ConfigDict(extra="allow")


class Attachment(_Record):
    filename: str


class ChatRecord(_Record):
    id: str
    thread_id: str
    author: str
    ts: str
    text: str
    attachments: list[Attachment]


class DocRecord(_Record):
    id: str
    format: Literal["pdf", "html", "md"]
    filename: str
    title: str
    body: str
    metadata: dict[str, str]


class TableRecord(_Record):
    id: str
    table: Literal["clientes", "transacciones", "pqrs", "empleados"]
    columns: dict[str, str]


RECORD_MODELS: dict[str, type[_Record]] = {
    "chats": ChatRecord,
    "docs": DocRecord,
    "tables": TableRecord,
}


class Pseudonyms(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    cedula: str | None = None
    handle: str | None = None
    address: str | None = None
    birth_iso: str | None = None
    plate: str | None = None
    account: str | None = None
    passport: str | None = None


class Entity(BaseModel):
    entity_id: str
    type: Literal["person", "organization_or_place"]
    originals: list[str]
    records: list[str]
    pseudonyms: Pseudonyms | None = None
    kept: bool | None = None
    reason: str | None = None


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    team: str
    version: str
    models: list[str]


class RunRequest(BaseModel):
    sources_url: str
    token: str = Field(repr=False)


class RunAccepted(BaseModel):
    job_id: str


class RecordCounts(BaseModel):
    chats: int = 0
    docs: int = 0
    tables: int = 0


class RunCost(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0


class RunStatus(BaseModel):
    status: JobStatus
    started_at: str | None = None
    finished_at: str | None = None
    records: RecordCounts | None = None
    cost: RunCost | None = None
    error: str | None = None


class AnonymizeRequest(BaseModel):
    source: Source
    records: list[dict] = Field(max_length=50)


class AnonymizeResponse(BaseModel):
    records: list[dict]
    entities: list[Entity]
