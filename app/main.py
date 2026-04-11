from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import uuid, os, json

load_dotenv()

from app.graph import app_graph
from app.qdrant_db import insert_data
from app.memory import get_chat, clear_chat, get_all_users

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
    print("🚀 Limbu.ai Chatbot v3 starting...")
    insert_data()
    print("✅ Ready!")


@app.get("/")
def root():
    return {"message": "Limbu.ai Chatbot API v3 ", "admin": "/admin"}


# ── Chat Endpoints ────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    user_id = req.user_id or str(uuid.uuid4())
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    result = app_graph.invoke({"user_id": user_id, "message": req.message})
    return ChatResponse(
        response=result.get("response", ""),
        user_id=user_id,
        intent=result.get("intent", "general")
    )


@app.post("/webhook/chat")
async def webhook_chat(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = body.get("message", "").strip()
    user_id = body.get("user_id") or request.headers.get("X-User-ID") or str(uuid.uuid4())

    if not message:
        raise HTTPException(status_code=400, detail="message required")

    result = app_graph.invoke({"user_id": user_id, "message": message})
    return {
        "response": result.get("response", ""),
        "user_id": user_id,
        "intent": result.get("intent", "general"),
        "status": "ok"
    }


# ── Admin APIs ────────────────────────────────────────────────────
@app.get("/api/admin/users")
def admin_get_users():
    """Saare users ki list with last message"""
    users = get_all_users()
    return {"total": len(users), "users": users}


@app.get("/api/admin/chat/{user_id}")
def admin_get_chat(user_id: str):
    """Ek user ki poori chat history"""
    history = get_chat(user_id)
    return {"user_id": user_id, "messages": history, "total": len(history)}


@app.delete("/api/admin/chat/{user_id}")
def admin_clear_chat(user_id: str):
    clear_chat(user_id)
    return {"message": f"Chat cleared for {user_id}"}


# ── Admin Dashboard ───────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    """Real-time admin dashboard"""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Limbu.ai Chat Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;height:100vh;display:flex;flex-direction:column}
.header{background:#16a34a;padding:14px 20px;display:flex;align-items:center;justify-content:space-between}
.header h1{color:white;font-size:18px;font-weight:700}
.header span{color:#bbf7d0;font-size:13px}
.live-dot{width:8px;height:8px;background:#4ade80;border-radius:50%;display:inline-block;margin-right:6px;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.container{display:flex;flex:1;overflow:hidden}
.sidebar{width:320px;background:#1e293b;border-right:1px solid #334155;display:flex;flex-direction:column}
.sidebar-header{padding:14px 16px;border-bottom:1px solid #334155;display:flex;align-items:center;justify-content:space-between}
.sidebar-header h2{font-size:14px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px}
.user-count{background:#16a34a;color:white;padding:2px 8px;border-radius:10px;font-size:12px}
.users-list{flex:1;overflow-y:auto}
.user-item{padding:12px 16px;border-bottom:1px solid #334155;cursor:pointer;transition:background .2s}
.user-item:hover{background:#273344}
.user-item.active{background:#1e3a2f;border-left:3px solid #16a34a}
.user-id{font-size:13px;color:#e2e8f0;font-weight:600;margin-bottom:3px;word-break:break-all}
.user-meta{font-size:11px;color:#64748b;margin-bottom:4px}
.user-last{font-size:12px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.msg-count{background:#1e3a2f;color:#4ade80;padding:1px 6px;border-radius:8px;font-size:11px;float:right}
.chat-area{flex:1;display:flex;flex-direction:column;background:#0f172a}
.chat-header{padding:14px 20px;background:#1e293b;border-bottom:1px solid #334155;display:flex;align-items:center;justify-content:space-between}
.chat-header h3{font-size:15px;color:#e2e8f0}
.chat-header span{font-size:12px;color:#64748b}
.messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:70%;padding:10px 14px;border-radius:16px;font-size:14px;line-height:1.5}
.msg.user{background:#1d4ed8;color:white;align-self:flex-end;border-bottom-right-radius:4px}
.msg.assistant{background:#1e293b;color:#e2e8f0;align-self:flex-start;border-bottom-left-radius:4px}
.msg-time{font-size:10px;opacity:.6;margin-top:4px}
.empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#475569;gap:12px}
.empty-state .icon{font-size:48px}
.refresh-btn{background:#16a34a;border:none;color:white;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:13px}
.refresh-btn:hover{background:#15803d}
.clear-btn{background:#dc2626;border:none;color:white;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:13px;margin-left:8px}
.no-users{padding:20px;text-align:center;color:#475569;font-size:14px}
</style>
</head>
<body>
<div class="header">
  <h1>🤖 Limbu.ai Chat Admin</h1>
  <span><span class="live-dot"></span>Live Dashboard</span>
</div>
<div class="container">
  <div class="sidebar">
    <div class="sidebar-header">
      <h2>Users</h2>
      <span class="user-count" id="userCount">0</span>
    </div>
    <div class="users-list" id="usersList">
      <div class="no-users">Loading...</div>
    </div>
  </div>
  <div class="chat-area">
    <div class="chat-header">
      <div>
        <h3 id="chatTitle">Select a user</h3>
        <span id="chatMeta"></span>
      </div>
      <div>
        <button class="refresh-btn" onclick="loadUsers()">🔄 Refresh</button>
        <button class="clear-btn" id="clearBtn" onclick="clearChat()" style="display:none">🗑️ Clear</button>
      </div>
    </div>
    <div class="messages" id="messages">
      <div class="empty-state">
        <div class="icon">💬</div>
        <p>Select a user to view chat history</p>
      </div>
    </div>
  </div>
</div>

<script>
let selectedUser = null;
let autoRefresh = null;

async function loadUsers() {
  try {
    const res = await fetch('/api/admin/users');
    const data = await res.json();
    document.getElementById('userCount').textContent = data.total;
    const list = document.getElementById('usersList');
    if (!data.users.length) {
      list.innerHTML = '<div class="no-users">No users yet</div>';
      return;
    }
    list.innerHTML = data.users.map(u => `
      <div class="user-item ${u.user_id === selectedUser ? 'active' : ''}" onclick="selectUser('${u.user_id}')">
        <div class="user-id">${u.user_id.substring(0, 20)}... <span class="msg-count">${u.message_count} msgs</span></div>
        <div class="user-meta">Last: ${u.last_active}</div>
        <div class="user-last">${u.last_message || 'No messages'}</div>
      </div>
    `).join('');
  } catch(e) { console.error(e); }
}

async function selectUser(userId) {
  selectedUser = userId;
  document.getElementById('clearBtn').style.display = 'inline-block';
  document.getElementById('chatTitle').textContent = userId.substring(0, 30) + '...';
  loadChat(userId);
  loadUsers(); // Refresh sidebar
}

async function loadChat(userId) {
  try {
    const res = await fetch(`/api/admin/chat/${userId}`);
    const data = await res.json();
    document.getElementById('chatMeta').textContent = `${data.total} messages`;
    const msgs = document.getElementById('messages');
    if (!data.messages.length) {
      msgs.innerHTML = '<div class="empty-state"><div class="icon">💬</div><p>No messages</p></div>';
      return;
    }
    msgs.innerHTML = data.messages.map(m => `
      <div class="msg ${m.role}">
        ${m.content}
        <div class="msg-time">${m.time || ''}</div>
      </div>
    `).join('');
    msgs.scrollTop = msgs.scrollHeight;
  } catch(e) { console.error(e); }
}

async function clearChat() {
  if (!selectedUser) return;
  if (!confirm('Clear this chat?')) return;
  await fetch(`/api/admin/chat/${selectedUser}`, {method: 'DELETE'});
  loadChat(selectedUser);
}

// Auto refresh every 10 seconds
loadUsers();
setInterval(() => {
  loadUsers();
  if (selectedUser) loadChat(selectedUser);
}, 10000);
</script>
</body>
</html>"""
    return html


# ── Utility ───────────────────────────────────────────────────────
@app.get("/history/{user_id}")
def get_history(user_id: str):
    return {"user_id": user_id, "history": get_chat(user_id)}


@app.delete("/history/{user_id}")
def delete_history(user_id: str):
    clear_chat(user_id)
    return {"message": f"Cleared for {user_id}"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0"}