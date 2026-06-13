import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.graph import run_agent
from db import get_connection, init_db
from ws_manager import manager

load_dotenv()

app = FastAPI(title="AI Customer Support Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


class ChatRequest(BaseModel):
    customer_id: str
    message: str


class ChatResponse(BaseModel):
    response: str
    decision: str
    customer_id: str


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/customers")
async def list_customers() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT customer_id, name, email, loyalty_tier, total_orders FROM customers ORDER BY customer_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not set. Copy .env.example to .env and add your key.",
        )
    try:
        result = await run_agent(request.customer_id, request.message)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ChatResponse(
        response=result["response"],
        decision=result["decision"],
        customer_id=result["customer_id"],
    )


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
