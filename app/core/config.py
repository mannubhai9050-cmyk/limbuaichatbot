import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # "anthropic" or "openai"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# ── WhatsApp ──────────────────────────────────────────────────────
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL", "")
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

# ── Social Media Connect ─────────────────────────────────────────
LIMBU_SOCIAL_CONNECT_URL = "https://limbu.ai/connect-business"
LIMBU_META_STATUS_API = "https://limbu.ai/api/chatbot/meta-connection"

# Supported platforms: facebook, instagram
SOCIAL_PLATFORMS = {
    "facebook": {
        "name": "Facebook",
        "emoji": "📘",
        "connect_url": "https://limbu.ai/connect-business?type=meta&source=chatbot&platform=facebook",
        "status_type": "facebook",
    },
    "instagram": {
        "name": "Instagram",
        "emoji": "📸",
        "connect_url": "https://limbu.ai/connect-business?type=meta&source=chatbot&platform=instagram",
        "status_type": "instagram",
        "page_key": "pageName",
        "id_key": "pageId",
    },
    "youtube": {
        "name": "YouTube",
        "emoji": "▶️",
        "connect_url": "https://limbu.ai/connect-business?type=youtube",
        "status_type": "youtube",
        "page_key": "channelTitle",
        "id_key": "channelId",
    },
    "linkedin": {
        "name": "LinkedIn",
        "emoji": "💼",
        "connect_url": "https://limbu.ai/connect-business?type=linkedin",
        "status_type": "linkedin",
        "page_key": "pageName",
        "id_key": "pageId",
    },
}

# ── App Settings ──────────────────────────────────────────────────
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MAX_CHAT_HISTORY = 100       # Keep last 20 messages only
SESSION_TTL = 2592000       # 30 days session
CHAT_TTL = 604800           # 7 days chat history
TIMEZONE = "Asia/Kolkata"