"""
Chat WebSocket route.
WS /chat — WebSocket proxying to Claude API with intelligence system context.
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.database import SessionLocal
from shared.models import Prediction, Event, WeakSignal
from shared.llm_client import call_claude_sonnet

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["chat"])

SYSTEM_PROMPT = """You are an intelligence analyst assistant embedded in a multi-agent 
intelligence prediction system. You have access to the system's current state including 
active predictions, recent events, and weak signals.

When answering questions:
- Reference specific predictions by their ID when relevant
- Provide confidence levels and evidence quality assessments
- Flag when information contradicts active predictions
- Suggest decision-relevant implications

Current system context will be provided with each message.
"""


def _build_context(db: Session) -> str:
    """Build a context string from current system state for the LLM."""
    parts = []

    # Active predictions summary
    active_preds = (
        db.query(Prediction)
        .filter(Prediction.status == "ACTIVE")
        .order_by(Prediction.created_at.desc())
        .limit(20)
        .all()
    )
    if active_preds:
        parts.append("## Active Predictions")
        for p in active_preds:
            parts.append(
                f"- [{p.id}] {p.claim} (confidence: {p.current_confidence:.0%}, agent: {p.agent})"
            )

    # Recent events
    recent_events = (
        db.query(Event)
        .order_by(Event.timestamp.desc())
        .limit(10)
        .all()
    )
    if recent_events:
        parts.append("\n## Recent Events")
        for e in recent_events:
            parts.append(
                f"- [{e.domain}] {e.raw_text[:150] if e.raw_text else 'No text'} "
                f"(integrity: {e.integrity_score or 'N/A'}, source: {e.source})"
            )

    # Weak signals
    signals = (
        db.query(WeakSignal)
        .order_by(WeakSignal.detected_at.desc())
        .limit(5)
        .all()
    )
    if signals:
        parts.append("\n## Weak Signals")
        for s in signals:
            parts.append(f"- [{s.strength}] {s.signal}")

    return "\n".join(parts) if parts else "No system data available yet."


@router.websocket("/chat")
async def chat_websocket(websocket: WebSocket):
    """
    WebSocket chat endpoint. Proxies messages to Claude API with system context.
    
    Client sends: {"message": "user text", "api_key": "..."}
    Server sends: {"response": "assistant text"} or {"error": "..."}
    """
    await websocket.accept()

    # Maintain conversation history for multi-turn
    conversation_history: list[dict] = []

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            user_message = payload.get("message", "").strip()
            api_key = payload.get("api_key", "")

            if not user_message:
                await websocket.send_json({"error": "Empty message"})
                continue

            # Validate API key
            if api_key != settings.API_KEY:
                await websocket.send_json({"error": "Invalid API key"})
                continue

            # Build system context from DB
            db = SessionLocal()
            try:
                context = _build_context(db)
            finally:
                db.close()

            # Compose the full user message with context
            augmented_message = (
                f"<system_context>\n{context}\n</system_context>\n\n"
                f"User question: {user_message}"
            )

            # Add to conversation history
            conversation_history.append({"role": "user", "content": augmented_message})

            # Keep history manageable (last 20 exchanges)
            if len(conversation_history) > 40:
                conversation_history = conversation_history[-40:]

            try:
                response_text = await call_claude_sonnet(
                    system_prompt=SYSTEM_PROMPT,
                    user_message=augmented_message,
                    max_tokens=2048,
                )
                conversation_history.append(
                    {"role": "assistant", "content": response_text}
                )
                await websocket.send_json({"response": response_text})
            except Exception as e:
                logger.error(f"LLM call failed: {e}")
                await websocket.send_json(
                    {"error": f"Analysis engine error: {str(e)}"}
                )

    except WebSocketDisconnect:
        logger.info("Chat WebSocket disconnected")
    except Exception as e:
        logger.error(f"Chat WebSocket error: {e}")
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
