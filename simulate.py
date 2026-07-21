"""
Local test — bot ko apne computer par chalao, bina kisi ko WhatsApp bheje.

Chalana:  python simulate.py

Button dabane ke liye uska ID likho (jaise: CONNECT_START)
Message likhne ke liye seedha text likho  (jaise: Sharma Sweets, Gurgaon)
'menu'  -> abhi ke buttons dobara dikhao
'reset' -> nayi conversation
'quit'  -> band karo
"""
import sys
import os

sys.path.insert(0, os.getcwd())
os.environ["PYTHONIOENCODING"] = "utf-8"

from unittest.mock import patch

# Fake WhatsApp — asli message kahin nahi jaayega, sab yahin screen par
SENT = []


def fake_post(payload):
    SENT.append(payload)
    return True


def show():
    for m in SENT:
        print()
        if m.get("type") == "media":
            print(f"  🖼️  [{m['media']['type'].upper()}] {m['media']['url']}")
        elif m.get("button"):
            print("  " + m["message"].replace("\n", "\n  "))
            print(f"  ┌─────────────── URL BUTTON ─────────────")
            print(f"  │  🔗 {m['button']['text']}  →  {m['button']['url']}")
            print(f"  └───────────────────────────────────────")
        elif "buttons" in m:
            print("  " + m["message"].replace("\n", "\n  "))
            print("  ┌─────────────── BUTTONS ───────────────")
            for b in m["buttons"]:
                print(f"  │  [{b['id']}]  {b['title']}")
            print("  └───────────────────────────────────────")
        elif "sections" in m:
            print("  " + m["message"].replace("\n", "\n  "))
            print("  ┌──────────────── LIST ─────────────────")
            for s in m["sections"]:
                for row in s["rows"]:
                    desc = f"  — {row.get('description','')}" if row.get("description") else ""
                    print(f"  │  [{row['id']}]  {row['title']}{desc}")
            print("  └───────────────────────────────────────")
        else:
            print("  " + m["message"].replace("\n", "\n  "))
    SENT.clear()


def main():
    with patch("app.services.whatsapp_service._post", fake_post):
        from app.flow import engine

        user = "wa_919999999999"
        phone = "919999999999"

        # nayi conversation — purana session hata do
        from app.services.redis_service import clear_session
        try:
            clear_session(user)
        except Exception:
            pass

        print("=" * 50)
        print("  LIMBU BOT — LOCAL TEST (koi asli message nahi jaayega)")
        print("=" * 50)
        print("  Button dabao: ID likho (jaise CONNECT_START)")
        print("  Message: seedha text likho")
        print("  reset / quit")
        print("=" * 50)

        # pehli screen
        engine.handle(user, phone, "", "")
        show()

        while True:
            try:
                inp = input("\n👉 You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not inp:
                continue
            if inp.lower() == "quit":
                break
            if inp.lower() == "reset":
                try:
                    clear_session(user)
                except Exception:
                    pass
                engine.handle(user, phone, "", "")
                show()
                continue

            # ID jaisa dikhe (BADA_CASE, underscore) to button, warna text
            is_button = inp.replace("_", "").isalnum() and inp.upper() == inp and "_" in inp
            if is_button or inp.isupper():
                engine.handle(user, phone, "", inp)
            else:
                engine.handle(user, phone, inp, "")
            show()

        print("\n👋 Bye")


if __name__ == "__main__":
    main()
