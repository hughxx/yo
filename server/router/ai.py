from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.utils.llm import chat

router = APIRouter(prefix="/api/ai", tags=["ai"])


class ChatRequest(BaseModel):
    prompt: str
    message: str


class ChatResponse(BaseModel):
    reply: str


@router.post("/chat", response_model=ChatResponse)
async def ai_chat(req: ChatRequest):
    messages = [
        {"role": "system", "content": req.prompt},
        {"role": "user",   "content": req.message},
    ]
    try:
        reply = await chat(messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return ChatResponse(reply=reply)
