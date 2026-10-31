from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.config import TEAM, VERSION, Settings, get_settings
from app.jobs import JobRunner
from app.pipeline import Pipeline, published_file, run_pipeline
from app.schemas import (
    RECORD_MODELS,
    AnonymizeRequest,
    AnonymizeResponse,
    Health,
    RunAccepted,
    RunRequest,
    RunStatus,
)

MEDIA_TYPES = {
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def create_app(settings: Settings | None = None, pipeline: Pipeline | None = None) -> FastAPI:
    settings = settings or get_settings()
    runner = JobRunner(settings, pipeline or run_pipeline)
    router = APIRouter(prefix="/v1")

    @router.get("/health", response_model=Health)
    def health() -> Health:
        return Health(team=TEAM, version=VERSION, models=settings.models)

    @router.post("/run", status_code=202, response_model=RunAccepted)
    def start_run(body: RunRequest) -> RunAccepted:
        return RunAccepted(job_id=runner.submit(body.sources_url, body.token))

    @router.get("/run/{job_id}", response_model=RunStatus, response_model_exclude_none=True)
    def run_status(job_id: str) -> RunStatus:
        status = runner.status(job_id)
        if status is None:
            raise HTTPException(404, "job no encontrado")
        return status

    def serve(name: str) -> FileResponse:
        path = published_file(settings.output_dir, name)
        if path is None:
            raise HTTPException(404, "no hay corrida terminada")
        return FileResponse(path, media_type=MEDIA_TYPES[path.suffix])

    @router.get("/output/{archivo}")
    def output(archivo: str) -> FileResponse:
        return serve(archivo)

    @router.get("/entities")
    def entities() -> FileResponse:
        return serve("entities.json")

    @router.post("/anonymize", response_model=AnonymizeResponse, response_model_exclude_none=True)
    def anonymize(body: AnonymizeRequest) -> AnonymizeResponse:
        model = RECORD_MODELS[body.source]
        records, errors = [], []
        for i, raw in enumerate(body.records):
            try:
                records.append(model.model_validate(raw).model_dump(mode="json"))
            except ValidationError as exc:
                for err in exc.errors(include_url=False, include_input=False):
                    errors.append({**err, "loc": ["body", "records", i, *err["loc"]]})
        if errors:
            raise HTTPException(422, errors)
        return AnonymizeResponse(records=records, entities=[])

    app = FastAPI(title="Kipu Shadow", version=VERSION)
    app.include_router(router)
    return app
