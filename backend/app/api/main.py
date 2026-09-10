import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.run_logger import set_main_event_loop
from app.api.routes import locations, reports, runs, search
from app.api.websocket import run_stream
from app.config.settings import get_settings

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    set_main_event_loop(asyncio.get_running_loop())
    yield


app = FastAPI(
    title="Docs — Public Records Research",
    description="Agentic public records research powered by NETR Online",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-PDF-Storage-Url", "X-PDF-Storage-Path"],
)

app.include_router(locations.router)
app.include_router(search.router)
app.include_router(runs.router)
app.include_router(reports.router)
app.include_router(run_stream.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
