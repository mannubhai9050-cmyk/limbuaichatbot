from langchain_anthropic import ChatAnthropic
from app.core.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

llm = ChatAnthropic(
    model=CLAUDE_MODEL,
    api_key=ANTHROPIC_API_KEY,
    temperature=0.7,
    max_tokens=1024
)