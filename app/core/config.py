import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyBFBrkcFEapAR7b1AuWovzq-fy4MsjmIfI")

# ── Limbu.ai API ──────────────────────────────────────────────────
LIMBU_API_BASE = "https://limbu.ai/api"
LIMBU_ADMIN_EMAIL = "info@limbu.ai"
LIMBU_CONNECT_URL = "http://limbu.ai/connect-google-business"
PLANS_API_URL = "https://www.limbu.ai/api/home-data?type=subscriptionPlans" 

# ── App Settings ──────────────────────────────────────────────────
MAX_CHAT_HISTORY = 20
SESSION_TTL = 3600        # 1 hour
CHAT_TTL = 604800         # 7 days
QDRANT_COLLECTION = "limbu_kb"
EMBEDDING_MODEL = "text-embedding-3-small"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
TIMEZONE = "Asia/Kolkata"