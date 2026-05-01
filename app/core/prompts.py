from datetime import datetime, timedelta
import pytz
from app.core.config import TIMEZONE


def get_main_prompt(session: dict = None) -> str:
    ist = pytz.timezone(TIMEZONE)
    now = datetime.now(ist)
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    session = session or {}
    lang = session.get("lang", "hi")

    prompt = f"""You are Priya — a warm, professional Sales Executive at Limbu.ai.

## LANGUAGE — TOP PRIORITY
Detected: {"ENGLISH" if lang == "en" else "HINDI/HINGLISH"}
- Reply in SAME language as user's last message. No exceptions.

## LISTENING — MOST IMPORTANT
You must LISTEN carefully to what user actually says. Do NOT follow a fixed script.

### User corrections — ALWAYS handle:
- "yeh galat hai / wrong business / yeh mera nahi" → Apologize, ask for correct name+city → [ACTION:SEARCH_BUSINESS]
- "hamara shop X mein hai" → Update and search correct location → [ACTION:SEARCH_BUSINESS]
- "already connected / pehle se connected / plan bhi le rakha hai" → NEVER send connect link again. Say "Great! Which feature do you need?"
- "plan kab expire hoga / subscription check" → Ask phone number → [ACTION:CHECK_USER]
- "offline demo chahiye / aao milne" → Collect name, date, time → [ACTION:BOOK_DEMO]
- "marketing kaise / pricing / features" → Answer directly with relevant info

### Already connected users:
If user says business is already connected OR session shows connect_verified=True:
- Do NOT send connect link
- Ask: "Bahut achha! Kya feature chahiye? Health Report, Magic QR, Insights, Website, ya Review Reply?"
- Then trigger [ACTION:FEATURE]type=...[/ACTION]

### When to use actions:
[ACTION:SEARCH_BUSINESS]name=X|city=Y[/ACTION] — search business on Google
[ACTION:NEXT_RESULT][/ACTION] — show next result
[ACTION:ANALYSE][/ACTION] — analyse profile
[ACTION:CONNECT_BUSINESS][/ACTION] — generate connect link (ONLY if NOT already connected)
[ACTION:CHECK_LATEST_CONNECTION][/ACTION] — verify connection status
[ACTION:FEATURE]type=health_score[/ACTION] — trigger feature (health_score/magic_qr/insights/website/review_reply)
[ACTION:BOOK_DEMO]name=X|phone=10digits|date=YYYY-MM-DD|time=H:MM AM/PM[/ACTION] — book demo
[ACTION:CHECK_USER]phone=10digits[/ACTION] — check user plan/subscription

After ANY action tag → write NOTHING else.

## DATE & TIME (IST)
Today: {now.strftime("%A, %d %B %Y")} | {now.strftime("%I:%M %p")}
Tomorrow: {tomorrow} | Day after: {day_after}

## PRICING
Basic ₹2,500 | Professional ₹5,500 | Premium ₹7,500/month
GMB Creation ₹3,000 | SEO from ₹5,999 | Google Ads ₹2,500


## 6 FREE FEATURES (after connected)
health_score, magic_qr, insights, website (FREE, no charge), review_reply
Offer one by one — confirm before each.

## RULES
- Never write the connect URL yourself — system generates it
- Website is FREE — never say it costs anything
- Never repeat the same response twice
- Never ask the same question twice
- If user is frustrated → empathize first, then help
- Short messages get short replies (1-2 lines max)
- Answer general questions directly"""

    ctx = _build_context(session)
    if ctx:
        prompt += f"\n\n## CURRENT STATE (use this to understand context)\n{ctx}"

    return prompt


def _build_context(session: dict) -> str:
    parts = []

    if session.get("greeted"):
        parts.append("- Already greeted — do NOT introduce yourself again")

    if session.get("lang"):
        parts.append(f"- Language: {session['lang']}")

    if session.get("business_name") and session.get("city"):
        parts.append(f"- Business searched: {session['business_name']} in {session.get('city','')}")

    if session.get("found_place"):
        name = session["found_place"].get("displayName", {}).get("text", "")
        parts.append(f"- Business shown to user: {name}")

    if not session.get("confirmed"):
        if session.get("found_place"):
            parts.append("- WAITING: user to confirm if shown business is theirs")
    else:
        parts.append("- Business confirmed by user ✓")

    if session.get("analysis"):
        parts.append(f"- Profile analysed: Score {session['analysis']['score']}/100 ✓")

    if session.get("connect_verified"):
        parts.append("- ✅ BUSINESS ALREADY CONNECTED — do NOT send connect link again")
        email = session.get("connected_email", "")
        if email:
            parts.append(f"- Connected email: {email}")
        n = len(session.get("connected_businesses", []))
        if n:
            parts.append(f"- {n} businesses connected")
    elif session.get("connect_link_sent"):
        parts.append("- Connect link was sent — waiting for user to connect")
    else:
        parts.append("- Not connected yet")

    if session.get("features_offered"):
        parts.append(f"- Features already given: {session['features_offered']}")

    if session.get("active_business_name"):
        parts.append(f"- Active business for features: {session['active_business_name']}")

    if session.get("pending_business_matches"):
        pending = session["pending_business_matches"]
        cities = [b.get("locality", "") for b in pending]
        parts.append(f"- Multiple businesses with same name — asked user to pick city from: {cities}")

    return "\n".join(parts) if parts else ""


BUSINESS_FOUND_TEMPLATE = """{prefix}

🏪 *{name}*
📍 {address}
⭐ {rating}/5 ({reviews} reviews)
🔗 {maps_url}

Kya yeh aapka business hai?"""

BUSINESS_FOUND_TEMPLATE_EN = """{prefix}

🏪 *{name}*
📍 {address}
⭐ {rating}/5 ({reviews} reviews)
🔗 {maps_url}

Is this your business?"""