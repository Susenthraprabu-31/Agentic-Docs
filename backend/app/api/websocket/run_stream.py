import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agents.run_logger import subscribe_run, unsubscribe_run
from app.db.repositories.runs_repository import RunsRepository

router = APIRouter()


@router.websocket("/runs/{run_id}/stream")
async def run_stream(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    repo = RunsRepository()

    run = repo.get_run(run_id)
    if not run:
        await websocket.send_json({"error": "Run not found"})
        await websocket.close()
        return

    existing = repo.get_events(run_id)
    for event in existing:
        await websocket.send_json(event)

    queue = subscribe_run(run_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event)
                if event.get("event_type") == "run_completed":
                    break
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                if run.get("status") in ("completed", "failed"):
                    updated = repo.get_run(run_id)
                    if updated and updated.get("status") in ("completed", "failed"):
                        break
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe_run(run_id, queue)
