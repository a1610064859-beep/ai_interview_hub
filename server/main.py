from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from server.api.jobs import router as jobs_router
from server.api.sessions import router as sessions_router
from server.api.reports import router as reports_router
from server.api.growth import router as growth_router
from server.api.recruiter import router as recruiter_router
from server.api.student_roster import router as student_roster_router
from server.api.counsel import router as counsel_router
from server.config import settings
from server.db import init_db
from server.services import asr


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    audio_dir = Path(settings.tts_output_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    if settings.asr_enabled and settings.asr_preload:
        await asr.warmup()
    yield


app = FastAPI(
    title="AI Interview Hub API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)
app.include_router(sessions_router)
app.include_router(reports_router)
app.include_router(growth_router)
app.include_router(recruiter_router)
app.include_router(student_roster_router)
app.include_router(counsel_router)


@app.get("/api/asr/status")
def get_asr_status():
    return asr.service_status()


@app.get("/audio/{filename:path}")
def get_audio_file(filename: str):
    audio_dir = Path(settings.tts_output_dir).resolve()
    file_path = (audio_dir / filename).resolve()
    if not file_path.is_relative_to(audio_dir):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(file_path, media_type="audio/mpeg")


