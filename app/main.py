from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import uuid

load_dotenv()

from app.graph import chat
from app.qdrant_db import insert_data
from app.services.redis_service import get_history, clear_history, get_all_users, r, get_session, save_message

app = FastAPI(title="Limbu.ai Chatbot API", version="4.0.0")

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
    print("🚀 Limbu.ai Chatbot v4 starting...")
    insert_data()
    print("✅ Ready!")


@app.get("/")
def root():
    return {"message": "Limbu.ai Chatbot API v4 🚀", "admin": "/admin"}


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    user_id = req.user_id or str(uuid.uuid4())
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    response = chat(user_id, req.message)
    return {"response": response, "user_id": user_id, "status": "ok"}


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
    response = chat(user_id, message)
    return {"response": response, "user_id": user_id, "status": "ok"}


@app.post("/webhook/connected")
async def webhook_connected(request: Request):
    """Auto-notify chatbot when user connects or fails to connect"""
    try:
        body = await request.json()

        status = body.get("status", "success")
        email = body.get("email", "")
        message = body.get("message", "")



        from app.nodes.connect import handle_check_latest_connection, handle_connect_link

        # Find user by phone
        phone = body.get("phone", "")
        user_id = None
        
        if phone:
            # WhatsApp user
            wa_id = f"wa_{phone}"
            sess = get_session(wa_id)
            if sess:
                user_id = wa_id
        


        if not user_id:
            return {"status": "session not found"}

        session = get_session(user_id)

        if status == "failed":
            new_link_reply = handle_connect_link(user_id, session)
            reply = (
                "Lagta hai galat Gmail account use hua. Kripya us Gmail se try karein "
                "jisme aapka Google Business Profile registered hai:\n\n"
                + new_link_reply
            )
        else:
            if email:
                session["connected_email"] = email
                save_session(user_id, session)
            reply = handle_check_latest_connection(user_id, session)

        save_message(user_id, "assistant", reply)
        return {"status": "ok", "user_id": user_id}

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


@app.post("/webhook/action-complete")
async def webhook_action_complete(request: Request):
    """Receive action completion from Limbu.ai dashboard"""
    try:
        body = await request.json()
        print(f"[Webhook Action] Received: {body}")
        
        phone = str(body.get("phone", "")).strip()
        action = body.get("action", "")
        status = body.get("status", "success")
        result = body.get("result", {})

        if not phone:
            return {"status": "error", "detail": "phone required"}

        # Find user_id by phone
        user_id = f"wa_{phone}"
        sess = get_session(user_id)
        if not sess:
            user_id = f"u_{phone}"
            sess = get_session(user_id)
        if not sess:
            print(f"[Webhook Action] No user found for phone: {phone}")
            return {"status": "user not found", "phone": phone}

        # Build message based on action and result
        action_labels = {
            "health_score": "GMB Health Score Report",
            "magic_qr": "Magic QR Code",
            "website": "Optimized Website",
            "insights": "GMB Insights",
            "review_reply": "Review Reply Setup",
            "keyword_planner": "Keyword Planner",
            "social_posts": "Social Media Posts"
        }
        label = action_labels.get(action, action)

        if status == "success":
            # Build rich message from result
            text = result.get("text") or result.get("message") or ""
            msg = f"✅ *{label} ready hai!*\n\n{text}"
            
            if result.get("pdf_url"):
                msg += f"\n\n📄 PDF Report: {result['pdf_url']}"
            if result.get("qr_url"):
                msg += f"\n\n🔮 QR Code: {result['qr_url']}"
            if result.get("website_url"):
                msg += f"\n\n🌐 Website: {result['website_url']}"
            if result.get("data") and action == "health_score":
                data = result["data"]
                score = data.get("totalScore", "")
                stat = data.get("status", "")
                if score:
                    msg += f"\n\n📊 Score: {score}/100 — {stat}"
            if result.get("keywords"):
                kw_list = result["keywords"]
                if isinstance(kw_list, list):
                    kw_text = "\n".join([f"  • {k.get('word',k)} — {k.get('volume','')}" for k in kw_list[:10]])
                    msg += f"\n\n🔑 Keywords:\n{kw_text}"
        else:
            msg = f"❌ {label} mein problem aayi. Kripya 📞 9283344726 par call karein."

        save_message(user_id, "assistant", msg)

        # Send via WhatsApp if user came from WhatsApp
        if user_id.startswith("wa_"):
            try:
                from app.services.whatsapp_service import send_whatsapp
                wa_phone = user_id.replace("wa_", "")
                send_whatsapp(wa_phone, msg)
                print(f"[Webhook Action] ✅ Sent to WhatsApp: {wa_phone}")
            except Exception as wa_e:
                print(f"[Webhook Action] WA send error: {wa_e}")

        return {"status": "ok", "user_id": user_id}

    except Exception as e:
        print(f"[Webhook Action] Error: {e}")
        import traceback; traceback.print_exc()
        return {"status": "error", "detail": str(e)}


@app.get("/analytics", response_class=HTMLResponse)
def analytics_dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Limbu.ai Analytics</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:linear-gradient(135deg,#16a34a,#059669);padding:16px 24px;display:flex;align-items:center;justify-content:space-between}
.header h1{color:white;font-size:20px;font-weight:700}
.header a{color:#bbf7d0;font-size:13px;text-decoration:none}
.tabs{display:flex;gap:4px;padding:16px 24px 0;background:#1e293b;border-bottom:1px solid #334155}
.tab{padding:10px 20px;border-radius:8px 8px 0 0;cursor:pointer;font-size:13px;font-weight:600;color:#64748b;transition:.15s}
.tab.active{background:#0f172a;color:#4ade80}
.content{padding:24px;display:none}
.content.active{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.card{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}
.card-label{font-size:12px;color:#64748b;margin-bottom:8px;text-transform:uppercase;letter-spacing:1px}
.card-value{font-size:32px;font-weight:700;color:#4ade80}
.card-sub{font-size:12px;color:#475569;margin-top:4px}
.table-wrap{background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155}
table{width:100%;border-collapse:collapse}
th{background:#162032;padding:12px 16px;text-align:left;font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:1px}
td{padding:12px 16px;border-bottom:1px solid #1a2535;font-size:13px}
tr:hover td{background:#1a2535}
.badge{padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600}
.badge-green{background:#0f3a1e;color:#4ade80}
.badge-blue{background:#1e3a5f;color:#60a5fa}
.badge-yellow{background:#3a2e0f;color:#fbbf24}
.badge-red{background:#3a0f0f;color:#f87171}
.dot{width:8px;height:8px;background:#4ade80;border-radius:50%;animation:pulse 1.5s infinite;display:inline-block;margin-right:6px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.funnel{display:flex;flex-direction:column;gap:8px;margin-bottom:24px}
.funnel-row{display:flex;align-items:center;gap:12px}
.funnel-bar{height:36px;background:#16a34a;border-radius:6px;min-width:4px;transition:width .5s}
.funnel-label{font-size:13px;color:#94a3b8;white-space:nowrap;width:200px}
.funnel-val{font-size:14px;font-weight:600;color:#4ade80}
.empty{padding:40px;text-align:center;color:#475569}
</style>
</head>
<body>
<div class="header">
  <h1>📊 Limbu.ai Analytics Dashboard</h1>
  <div style="display:flex;gap:16px;align-items:center">
    <span style="color:#bbf7d0;font-size:13px"><span class="dot"></span>Live</span>
    <a href="/admin">💬 Chat Admin</a>
  </div>
</div>
<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('connections')">Connections</div>
  <div class="tab" onclick="showTab('payments')">Payments</div>
</div>

<div id="overview" class="content active">
  <div class="cards" id="cards">Loading...</div>
  <h3 style="margin-bottom:12px;color:#94a3b8;font-size:14px">CONVERSION FUNNEL</h3>
  <div class="funnel" id="funnel"></div>
  <h3 style="margin-bottom:12px;color:#94a3b8;font-size:14px">TODAY'S ACTIVITY</h3>
  <div class="cards" id="today-cards"></div>
</div>

<div id="connections" class="content">
  <div class="table-wrap">
    <table>
      <thead><tr><th>Time</th><th>User ID</th><th>Email</th><th>Businesses</th></tr></thead>
      <tbody id="conn-tbody"><tr><td colspan="4" class="empty">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

<div id="payments" class="content">
  <div class="table-wrap">
    <table>
      <thead><tr><th>Time</th><th>User ID</th><th>Plan</th><th>Amount</th><th>Email</th></tr></thead>
      <tbody id="pay-tbody"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

<script>
function showTab(name){
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.remove('active')});
  document.querySelectorAll('.content').forEach(c=>c.classList.remove('active'));
  document.querySelector(`#${name}`).classList.add('active');
  event.target.classList.add('active');
}

const labels = {
  business_searched:'Businesses Searched',business_confirmed:'Businesses Confirmed',
  analysis_done:'Analyses Done',business_connected:'Businesses Connected',
  feature_health_score:'Health Score',feature_insights:'Insights',
  feature_magic_qr:'Magic QR',feature_review_reply:'Review Reply',
  feature_keyword_planner:'Keyword Planner',plan_viewed:'Plans Viewed',
  payment_done:'Payments Done',demo_booked:'Demos Booked',whatsapp_message:'WhatsApp Messages'
};

async function loadStats(){
  const d = await(await fetch('/api/admin/stats')).json();
  
  // Main cards
  const mainKeys = ['business_connected','payment_done','demo_booked','analysis_done','whatsapp_message'];
  document.getElementById('cards').innerHTML = mainKeys.map(k=>`
    <div class="card">
      <div class="card-label">${labels[k]||k}</div>
      <div class="card-value">${d[k]||0}</div>
      <div class="card-sub">Today: ${d.today?.[k]||0}</div>
    </div>`).join('');

  // Funnel
  const funnelKeys = ['business_searched','business_confirmed','analysis_done','business_connected','payment_done'];
  const maxVal = Math.max(...funnelKeys.map(k=>d[k]||0), 1);
  document.getElementById('funnel').innerHTML = funnelKeys.map((k,i)=>{
    const val = d[k]||0;
    const w = Math.max((val/maxVal)*400, 4);
    const colors = ['#16a34a','#059669','#0d9488','#0891b2','#7c3aed'];
    return `<div class="funnel-row">
      <div class="funnel-label">${labels[k]||k}</div>
      <div class="funnel-bar" style="width:${w}px;background:${colors[i]}"></div>
      <div class="funnel-val">${val}</div>
    </div>`;
  }).join('');

  // Today cards
  const todayKeys = ['business_searched','analysis_done','business_connected','payment_done'];
  document.getElementById('today-cards').innerHTML = todayKeys.map(k=>`
    <div class="card">
      <div class="card-label">Today — ${labels[k]||k}</div>
      <div class="card-value" style="color:#60a5fa">${d.today?.[k]||0}</div>
    </div>`).join('');
}

async function loadConnections(){
  const d = await(await fetch('/api/admin/connections')).json();
  const tbody = document.getElementById('conn-tbody');
  if(!d.connections?.length){tbody.innerHTML='<tr><td colspan="4" class="empty">No connections yet</td></tr>';return;}
  tbody.innerHTML = d.connections.map(c=>`<tr>
    <td>${c.time||''}</td>
    <td style="font-size:11px;color:#64748b">${(c.user_id||'').slice(0,20)}...</td>
    <td>${c.email||'-'}</td>
    <td><span class="badge badge-green">${c.businesses||0} profile(s)</span></td>
  </tr>`).join('');
}

async function loadPayments(){
  const d = await(await fetch('/api/admin/payments')).json();
  const tbody = document.getElementById('pay-tbody');
  if(!d.payments?.length){tbody.innerHTML='<tr><td colspan="5" class="empty">No payments yet</td></tr>';return;}
  tbody.innerHTML = d.payments.map(p=>`<tr>
    <td>${p.time||''}</td>
    <td style="font-size:11px;color:#64748b">${(p.user_id||'').slice(0,20)}...</td>
    <td><span class="badge badge-blue">${p.plan||'-'}</span></td>
    <td><span class="badge badge-green">${p.amount||'-'}</span></td>
    <td>${p.email||'-'}</td>
  </tr>`).join('');
}

loadStats();loadConnections();loadPayments();
setInterval(()=>{loadStats();loadConnections();loadPayments();}, 10000);
</script>
</body>
</html>"""

@app.get("/health")
def health():
    return {"status": "ok", "version": "4.0.0"}


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
.chat-top span{font-size:12px;color:#64748b}
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
  <h1>🤖 Limbu.ai Chat Admin</h1>
  <div class="live"><div class="dot"></div>Live • Auto-refresh 10s</div>
</div>
<div class="body">
  <div class="sidebar">
    <div class="sidebar-top"><h2>Conversations</h2><span class="badge" id="cnt">0</span></div>
    <div class="users" id="users"><div class="no-users">Loading...</div></div>
  </div>
  <div class="chat">
    <div class="chat-top">
      <div><h3 id="ctitle">Select a conversation</h3><span id="cmeta"></span></div>
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
      <div class="uid">${u.user_id.slice(0,32)}... <span class="ucnt">${u.message_count}</span></div>
      <div class="umeta">${u.last_active}</div>
      <div class="ulast">${u.last_message||'No messages'}</div>
    </div>`).join('');
  }catch(e){console.error(e)}
}
async function selUser(uid){
  sel=uid;
  document.getElementById('cbtn').style.display='inline-block';
  document.getElementById('ctitle').textContent=uid.slice(0,40)+'...';
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
  sel=null;
  loadUsers();
}
loadUsers();
setInterval(()=>{loadUsers();if(sel)loadChat(sel);},10000);
</script>
</body>
</html>"""