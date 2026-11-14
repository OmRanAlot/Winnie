from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix = "/api", tags=["messages"])

class IncomingMessage(BaseModel):
    text: str

@router.post("/messages")

def handle_message(message: IncomingMessage):
    text = message.text.strip().lower()

    if text == "ping":
        reply = "pong from Python 🐼🏓"

    else:
        reply = "Winnie's Python backend received your message."

    return {"reply": reply}

