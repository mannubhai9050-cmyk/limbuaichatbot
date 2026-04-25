import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# ── Limbu.ai API ──────────────────────────────────────────────────
LIMBU_API_BASE = "https://limbu.ai/api"
LIMBU_ADMIN_EMAIL = "info@limbu.ai"
LIMBU_CONNECT_URL = "http://limbu.ai/connect-google-business"
PLANS_API_URL = "https://www.limbu.ai/api/home-data?type=subscriptionPlans"
CHATBOT_ACTION_API = "https://limbu.ai/api/chatbot/action"
CHATBOT_ACTION_RESULT_API = "https://limbu.ai/api/chatbot/action/result"
CHATBOT_WEBHOOK_URL = "https://limbubot.limbutech.in/webhook/action-complete"
WHATSAPP_API_URL = "https://whatsapp-one-blond.vercel.app/api/external/send"
WHATSAPP_API_KEY = "ws_2870c7f6bc8510381dc45e74df26a870d69f0512b17abade" 

# ── App Settings ──────────────────────────────────────────────────
MAX_CHAT_HISTORY = 100
SESSION_TTL = 3600        # 1 hour
CHAT_TTL = 604800         # 7 days
QDRANT_COLLECTION = "limbu_kb"
EMBEDDING_MODEL = "text-embedding-3-small"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
TIMEZONE = "Asia/Kolkata"