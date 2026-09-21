from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.api.jobs import router as jobs_router
from server.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Interview Hub API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)

