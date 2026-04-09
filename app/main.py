from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import uuid

load_dotenv()

from app.graph import app_graph
from app.qdrant_db import insert_data
from app.memory import get_chat, clear_chat

app = FastAPI(title="Limbu.ai Chatbot API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    user_id: str = None


class ChatResponse(BaseModel):
    response: str
    user_id: str
    intent: str


@app.on_event("startup")
def startup():
    print("🚀 Starting Limbu.ai Chatbot v3...")
    insert_data()
    print("✅ Server ready!")


@app.get("/")
def root():
    return {"message": "Limbu.ai Chatbot API v3 running 🚀"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    user_id = req.user_id or str(uuid.uuid4())
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    result = app_graph.invoke({"user_id": user_id, "message": req.message})
    return ChatResponse(
        response=result["response"],
        user_id=user_id,
        intent=result.get("intent", "general")
    )


@app.get("/history/{user_id}")
def get_history(user_id: str):
    return {"user_id": user_id, "history": get_chat(user_id)}


@app.delete("/history/{user_id}")
def delete_history(user_id: str):
    clear_chat(user_id)
    return {"message": f"History cleared for {user_id}"}


@app.get("/health")
def health():
    return {"status": "healthy", "version": "3.0.0"}