import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# ── WhatsApp ──────────────────────────────────────────────────────
WHATSAPP_API_URL = "https://whatsapp-one-blond.vercel.app/api/external/send"
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")

# ── Limbu.ai API ──────────────────────────────────────────────────
LIMBU_API_BASE = "https://limbu.ai/api"
LIMBU_ADMIN_EMAIL = "info@limbu.ai"
LIMBU_CONNECT_URL = "https://limbu.ai/connect-google-business"

# Plans API — fetch from Limbu backend
PLANS_API_URL = os.getenv("PLANS_API_URL", "https://limbu.ai/api/plans")

# Action APIs — trigger dashboard action + poll result
# POST: trigger action
CHATBOT_ACTION_API = os.getenv(
    "CHATBOT_ACTION_API",
    "https://limbu.ai/api/chatbot/action"
)
# GET: poll result
# e.g. https://limbu.ai/api/chatbot/action/result?phone=91XXXXXXXXXX&action=health_score
CHATBOT_ACTION_RESULT_API = os.getenv(
    "CHATBOT_ACTION_RESULT_API",
    "https://limbu.ai/api/chatbot/action/result"
)

# ── App Settings ──────────────────────────────────────────────────
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MAX_CHAT_HISTORY = 20       # Keep last 20 messages only
SESSION_TTL = 7200          # 2 hours session
CHAT_TTL = 604800           # 7 days chat history
TIMEZONE = "Asia/Kolkata"