from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from server.api.jobs import router as jobs_router
from server.api.sessions import router as sessions_router
from server.api.reports import router as reports_router
from server.config import settings
from server.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    audio_dir = Path(settings.tts_output_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="AI Interview Hub API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)
app.include_router(sessions_router)
app.include_router(reports_router)


@app.get("/audio/{filename:path}")
def get_audio_file(filename: str):
    audio_dir = Path(settings.tts_output_dir).resolve()
    file_path = (audio_dir / filename).resolve()
    if not file_path.is_relative_to(audio_dir):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(file_path, media_type="audio/mpeg")


