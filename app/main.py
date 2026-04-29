from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import uuid

load_dotenv()

from app.graph import chat
from app.services.redis_service import (
    get_history, clear_history, get_all_users,
    r, get_session, save_message, save_session
)

app = FastAPI(title="Limbu.ai WhatsApp Chatbot", version="5.0.0")

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


@app.on_event("startup")
def startup():
    print("🚀 Limbu.ai Chatbot v5 starting...")
    print("✅ Ready!")


@app.get("/")
def root():
    return {"message": "Limbu.ai Chatbot API v5 🚀", "admin": "/admin"}


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    user_id = req.user_id or str(uuid.uuid4())
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    response = chat(user_id, req.message)
    return {"response": response, "user_id": user_id, "status": "ok"}


@app.post("/webhook/chat")
async def webhook_chat(request: Request):
    """Main WhatsApp webhook endpoint"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = body.get("message", "").strip()
    user_id = (
        body.get("user_id") or
        request.headers.get("X-User-ID") or
        str(uuid.uuid4())
    )

    if not message:
        raise HTTPException(status_code=400, detail="message required")

    # ── Save phone in session if sent in webhook body ──────────────
    raw_phone = (
        body.get("phone") or
        body.get("from") or
        body.get("sender") or
        ""
    )
    if raw_phone:
        phone = raw_phone.replace("+", "").replace(" ", "").replace("-", "")
        if not phone.startswith("91") and len(phone) == 10:
            phone = "91" + phone
        # Save phone in session for feature actions
        from app.services.redis_service import get_session, save_session
        sess = get_session(user_id)
        if not sess.get("connect_phone"):
            sess["connect_phone"] = phone
            save_session(user_id, sess)

    response = chat(user_id, message)
    return {"response": response, "user_id": user_id, "status": "ok"}


@app.post("/webhook/connected")
async def webhook_connected(request: Request):
    """Called by Limbu.ai when user completes Google OAuth connect"""
    try:
        body = await request.json()
        phone = body.get("phone", "").replace("+", "").replace(" ", "")
        status = body.get("status", "success")
        email = body.get("email", "")

        if not phone:
            raise HTTPException(status_code=400, detail="phone required")

        # Normalize phone — ensure 91 prefix
        if not phone.startswith("91") and len(phone) == 10:
            phone = "91" + phone

        from app.nodes.connect import handle_check_latest_connection, handle_connect_link

        # Find user_id by phone (wa_917740847114 format)
        user_id = f"wa_{phone}"

        # Also check without 91 prefix as fallback
        session = get_session(user_id)
        if not session:
            user_id_alt = f"wa_{phone[2:]}" if phone.startswith("91") else f"wa_91{phone}"
            session = get_session(user_id_alt)
            if session:
                user_id = user_id_alt

        if not session:
            return {"status": "user session not found", "phone": phone}

        if status == "failed":
            new_link_reply = handle_connect_link(user_id, session)
            reply = (
                "Lagta hai galat Gmail account use hua. Kripya us Gmail se try karein "
                "jisme Google Business Profile registered hai:\n\n"
                + new_link_reply
            )
        else:
            if email:
                session["connected_email"] = email
                save_session(user_id, session)
            reply = handle_check_latest_connection(user_id, session)

        save_message(user_id, "assistant", reply)
        return {"status": "ok", "user_id": user_id, "phone": phone}

    except Exception as e:
        print(f"[Webhook Connected] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Admin APIs ────────────────────────────────────────────────────
@app.get("/api/admin/users")
def admin_users():
    users = get_all_users()
    return {"total": len(users), "users": users}


@app.get("/api/admin/chat/{user_id}")
def admin_chat(user_id: str):
    history = get_history(user_id)
    return {"user_id": user_id, "messages": history, "total": len(history)}


@app.delete("/api/admin/chat/{user_id}")
def admin_clear(user_id: str):
    clear_history(user_id)
    return {"message": f"Cleared for {user_id}"}


@app.get("/history/{user_id}")
def get_history_endpoint(user_id: str):
    return {"user_id": user_id, "history": get_history(user_id)}


@app.delete("/history/{user_id}")
def delete_history(user_id: str):
    clear_history(user_id)
    return {"message": f"Cleared for {user_id}"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "5.0.0"}


# ── Admin Dashboard ───────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Limbu.ai Chat Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;height:100vh;display:flex;flex-direction:column}
.header{background:linear-gradient(135deg,#16a34a,#059669);padding:14px 24px;display:flex;align-items:center;justify-content:space-between}
.header h1{color:white;font-size:18px;font-weight:700}
.live{display:flex;align-items:center;gap:6px;color:#bbf7d0;font-size:13px}
.dot{width:8px;height:8px;background:#4ade80;border-radius:50%;animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.body{display:flex;flex:1;overflow:hidden}
.sidebar{width:340px;background:#1e293b;border-right:1px solid #334155;display:flex;flex-direction:column}
.sidebar-top{padding:12px 16px;border-bottom:1px solid #334155;display:flex;align-items:center;justify-content:space-between}
.sidebar-top h2{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:1px}
.badge{background:#16a34a;color:white;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}
.users{flex:1;overflow-y:auto}
.user{padding:12px 16px;border-bottom:1px solid #1a2535;cursor:pointer;transition:all .15s}
.user:hover{background:#273344}
.user.active{background:#1a2e22;border-left:3px solid #16a34a}
.uid{font-size:12px;color:#94a3b8;margin-bottom:3px;word-break:break-all}
.umeta{font-size:11px;color:#475569;margin-bottom:3px}
.ulast{font-size:12px;color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ucnt{float:right;background:#0f3a1e;color:#4ade80;padding:1px 6px;border-radius:8px;font-size:11px}
.chat{flex:1;display:flex;flex-direction:column}
.chat-top{padding:12px 20px;background:#1e293b;border-bottom:1px solid #334155;display:flex;align-items:center;justify-content:space-between}
.chat-top h3{font-size:14px;color:#e2e8f0;font-weight:600}
.btns{display:flex;gap:8px}
.btn{padding:5px 12px;border:none;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600}
.btn-r{background:#1e3a2f;color:#4ade80}
.btn-c{background:#3b1e1e;color:#f87171}
.messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:72%;padding:10px 14px;border-radius:16px;font-size:13px;line-height:1.55;white-space:pre-wrap;word-break:break-word}
.msg.user{background:#1d4ed8;color:white;align-self:flex-end;border-bottom-right-radius:4px}
.msg.assistant{background:#1e293b;color:#e2e8f0;align-self:flex-start;border-bottom-left-radius:4px}
.mtime{font-size:10px;opacity:.5;margin-top:4px}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#475569;gap:10px}
.no-users{padding:20px;text-align:center;color:#475569;font-size:13px}
</style>
</head>
<body>
<div class="header">
  <h1>🤖 Limbu.ai Chat Admin v5</h1>
  <div class="live"><div class="dot"></div>Live • Auto-refresh 10s</div>
</div>
<div class="body">
  <div class="sidebar">
    <div class="sidebar-top"><h2>Conversations</h2><span class="badge" id="cnt">0</span></div>
    <div class="users" id="users"><div class="no-users">Loading...</div></div>
  </div>
  <div class="chat">
    <div class="chat-top">
      <div><h3 id="ctitle">Select a conversation</h3><span id="cmeta" style="font-size:12px;color:#64748b"></span></div>
      <div class="btns">
        <button class="btn btn-r" onclick="loadUsers()">↺ Refresh</button>
        <button class="btn btn-c" id="cbtn" onclick="doClear()" style="display:none">🗑 Clear</button>
      </div>
    </div>
    <div class="messages" id="msgs">
      <div class="empty"><div style="font-size:40px">💬</div><p>Select a conversation to view</p></div>
    </div>
  </div>
</div>
<script>
let sel=null;
async function loadUsers(){
  try{
    const d=await(await fetch('/api/admin/users')).json();
    document.getElementById('cnt').textContent=d.total;
    const el=document.getElementById('users');
    if(!d.users.length){el.innerHTML='<div class="no-users">No conversations yet</div>';return;}
    el.innerHTML=d.users.map(u=>`<div class="user ${u.user_id===sel?'active':''}" onclick="selUser('${u.user_id}')">
      <div class="uid">${u.user_id.slice(0,36)} <span class="ucnt">${u.message_count}</span></div>
      <div class="umeta">${u.last_active}</div>
      <div class="ulast">${u.last_message||''}</div>
    </div>`).join('');
  }catch(e){console.error(e)}
}
async function selUser(uid){
  sel=uid;
  document.getElementById('cbtn').style.display='inline-block';
  document.getElementById('ctitle').textContent=uid.slice(0,44)+'...';
  await loadChat(uid);loadUsers();
}
async function loadChat(uid){
  try{
    const d=await(await fetch('/api/admin/chat/'+encodeURIComponent(uid))).json();
    document.getElementById('cmeta').textContent=d.total+' messages';
    const el=document.getElementById('msgs');
    if(!d.messages.length){el.innerHTML='<div class="empty"><div style="font-size:40px">💬</div><p>No messages</p></div>';return;}
    el.innerHTML=d.messages.map(m=>`<div class="msg ${m.role}">${m.content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}<div class="mtime">${m.time||''}</div></div>`).join('');
    el.scrollTop=el.scrollHeight;
  }catch(e){console.error(e)}
}
async function doClear(){
  if(!sel||!confirm('Clear this conversation?'))return;
  await fetch('/api/admin/chat/'+encodeURIComponent(sel),{method:'DELETE'});
  document.getElementById('ctitle').textContent='Select a conversation';
  document.getElementById('cmeta').textContent='';
  document.getElementById('cbtn').style.display='none';
  sel=null;loadUsers();
}
loadUsers();
setInterval(()=>{loadUsers();if(sel)loadChat(sel);},10000);
</script>
</body>
</html>"""