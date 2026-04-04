import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import session_store
from routers import auth_router, chat_router, marksheet_router, transcribe_router, realtime_router

app = FastAPI(title="PM Youth Program's Portal API", version="1.0.0")

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(marksheet_router.router, prefix="/api/marksheet", tags=["marksheet"])
app.include_router(chat_router.router, prefix="/api/chat", tags=["chat"])
app.include_router(transcribe_router.router, prefix="/api", tags=["transcribe"])
app.include_router(realtime_router.router, prefix="/api/realtime")


@app.get("/api/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.get("/api/session/{session_id}", tags=["session"])
async def get_session(session_id: str):
    session = session_store.get(session_id)
    if not session:
        return {"session_id": session_id, "marksheet_uploaded": False, "history": []}
    return {
        "session_id": session_id,
        "marksheet_uploaded": session.marksheet_text is not None,
        "marksheet_summary": session.marksheet_summary,
        "history": session.history,
    }


async def _cleanup_loop():
    while True:
        await asyncio.sleep(600)  # every 10 minutes
        session_store.cleanup_old_sessions()


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_cleanup_loop())


# ── Serve frontend static files ──────────────────────────────
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")


@app.get("/app.html", response_class=HTMLResponse)
async def serve_app_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "app.html"))


@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    """Catch-all: return the requested file or fall back to index.html."""
    file_path = os.path.join(FRONTEND_DIR, full_path)
    if full_path and os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
