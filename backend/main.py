import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from database import create_tables, get_db, SessionLocal
from delegation_engine import graph_store
from websocket import manager as ws_manager
from routes import auth, topics, proposals, delegations, votes, admin, users

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Liquid Democracy API",
    description="Vote directly or delegate your vote on specific topics.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(topics.router)
app.include_router(proposals.router)
app.include_router(delegations.router)
app.include_router(votes.router)
app.include_router(admin.router)
app.include_router(users.router)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/proposals/{proposal_id}")
async def proposal_websocket(websocket: WebSocket, proposal_id: str):
    await ws_manager.connect(proposal_id, websocket)
    try:
        while True:
            # Keep connection alive; client sends pings as needed
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(proposal_id, websocket)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup() -> None:
    log.info("Creating database tables…")
    create_tables()

    log.info("Rebuilding delegation graphs from DB…")
    db = SessionLocal()
    try:
        graph_store.rebuild_from_db(db)
    finally:
        db.close()

    log.info("Startup complete.")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}
