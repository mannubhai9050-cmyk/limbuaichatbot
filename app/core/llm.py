"""
LLM provider — supports both Anthropic Claude and OpenAI GPT.
Set LLM_PROVIDER=openai in .env to use OpenAI.
"""
import os
from app.core.config import LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENAI_MODEL

# temperature 0.3 — low, taaki AI facts se chipke rahe aur apni taraf se plans/
# company ki galat baat na banaye (pehle 0.7 tha, zyada "creative").
if LLM_PROVIDER == "openai":
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        temperature=0.3,
        max_tokens=1000,
    )
    print(f"[LLM] Using OpenAI: {OPENAI_MODEL}")
else:
    from langchain_anthropic import ChatAnthropic
    llm = ChatAnthropic(
        model="claude-sonnet-4-5",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=1000,
    )
    print(f"[LLM] Using Anthropic: claude-sonnet-4-5")