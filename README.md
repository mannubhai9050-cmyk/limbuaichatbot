# Limbu.ai WhatsApp Chatbot v6

Button-based WhatsApp bot. Flow fixed hai; AI sirf tab bolta hai jab user
button ke bajaye apna text likhe.

## Kaise chalta hai

```
User button dabata hai  ->  button_payload  ->  flow engine  ->  agla screen
                            (koi LLM nahi, koi cost nahi, hamesha same)

User text likhta hai    ->  input screen ka action  (naam/city expect ho to)
                        ->  warna AI fallback: jawab + wahi buttons wapas
```

## Files

| File | Kaam |
|---|---|
| `flows/main.json` | **Poora flow** — screens, text, buttons, price. Code mein text nahi. |
| `app/flow/loader.py` | Startup par flow validate (limits, dangling next, duplicate id) |
| `app/flow/engine.py` | Button routing + screen render |
| `app/flow/actions.py` | Flow ko asli kaam se jodta hai (search, analyse, connect...) |
| `app/ai/fallback.py` | AI — sirf free text par |
| `app/services/whatsapp_service.py` | Sender: text/buttons/list/media/template + retry |
| `tests/test_flow.py` | 32 tests |

## Flow badalna

Text, price, button, screen — sab `flows/main.json` mein. **Python chhune ki
zaroorat nahi.** Save karke restart karein; galti ho to server start hi nahi
hoga aur wajah bata dega.

Naya screen jodne ke liye bas `screens` mein entry daalein aur kisi button ka
`next` usse jod dein.

## WhatsApp ki hard limits (loader inhe enforce karta hai)

- buttons: **max 3** per screen (zyada ke liye `type: "list"`)
- button title: **max 20 characters**
- list: **max 10 rows**, aur list ke saath media header nahi chalta
- free-form buttons sirf **24 ghante** ke andar; uske baad approved template

## Chalana

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest -q
```

`.env` chahiye: `OPENAI_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `REDIS_URL`,
`GOOGLE_API_KEY`, `WHATSAPP_API_URL`, `WHATSAPP_API_KEY`

## Abhi ke pending kaam

1. **Media URLs** — `flows/main.json` mein `<<<...>>>` wale placeholder hain
   (welcome banner, franchise video). Asli public URL daalne tak woh screens
   sirf text bhejti hain (skip hoti hain, crash nahi).
2. **`.env` mein purana WhatsApp URL** — `whatsapp-one-blond.vercel.app` likha
   hai jabki asli `whatsapp.limbu.ai` hai.
3. **Do webhook ek saath active hain** us WhatsApp platform par — ek hi message
   do bot ko jaata hai. Confirm karein ki dusra bot reply to nahi kar raha.
4. **Webhook signature verify nahi hoti** — platform `X-Webhook-Signature:
   sha256=...` bhejta hai, hum check nahi karte. Abhi koi bhi nakli message
   bhej sakta hai.
5. **Versions pinned nahi** — deploy se pehle lock karein.
6. **Image + buttons ek message mein** — platform se confirm karna hai ki
   support hai ya nahi. Abhi media alag message mein jaati hai.

## v5 se kya badla

- `graph.py` (1533 lines, 560-line if-else ladder) → `flow/engine.py` (~230 lines)
- Har message par LLM → **sirf free text par** LLM
- Button match **`button_payload` (ID)** se, label text se nahi — spelling
  lists (`"intrested"`, `"i am intrested"`) ki zaroorat khatam
- Price 4 files mein alag-alag thi (KB ₹3,500 vs baaki ₹2,500) → ek source
- Support number `connect.py` mein 8 jagah **galat** tha (`9283344726`) → ab
  `config.SUPPORT_PHONE`
- Phone normalize 5 jagah, 2 ulte convention → ek function
- Franchise/demo fail hone par bhi "ho gaya" bolta tha → ab sach bolta hai
- Follow-ups `threading.Timer` (restart par gayab) → Redis queue
- Action dedup in-memory (multi-worker par duplicate report) → Redis `SET NX`
- Message dedup in-memory → Redis
- Blocking I/O `async` handler mein → `run_in_threadpool`
- `print` → `logging` (phone ka sirf last 4 digit)
- 0 tests → 32 tests

## Jo jaan-boojh kar wapas nahi laaya gaya

**Sales intelligence** (`user_intelligence.py`, `conversation_memory.py`) —
uska scoring ulta chal raha tha: `"not interested"` par **+20 phir −20 = 0**
(kyunki `"interested"` uske andar substring hai) aur `"busy"` par **+15**
(kyunki `"buy"` uske andar hai) — yani rejection par positive score. Button
flow mein user ka intent button se hi pata chal jaata hai. Sahi version
chahiye to bataiye.
