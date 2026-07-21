"""
Flow tests. Koi asli message, Redis ya API call nahi — sab fake.

Chalane ke liye:  pytest -q

Project mein pehle ek bhi test nahi tha. Yeh woh bugs pakadte hain jo
rebuild ke dauraan asal mein mile the.
"""
import pytest
from unittest.mock import patch

FAKE_PLACE = {
    "id": "p1",
    "displayName": {"text": "Sharma Sweets"},
    "formattedAddress": "Sector 48, Gurgaon",
    "rating": 4.2,
    "userRatingCount": 37,
}


class Bot:
    """Fake WhatsApp + Redis ke saath engine chalata hai."""

    def __init__(self):
        self.sent = []
        self.store = {}
        self.user = "wa_919999999999"
        self.phone = "919999999999"

    def __enter__(self):
        self._p = [
            patch("app.services.whatsapp_service._post", self._send),
            patch("app.services.redis_service.get_session", self.store.get),
            patch("app.services.redis_service.save_session", self.store.__setitem__),
            patch("app.services.redis_service.save_message", lambda *a, **k: None),
            patch("app.services.redis_service.get_history", lambda u: []),
        ]
        for p in self._p:
            p.start()

        import app.flow.actions as A
        import app.flow.engine as E

        E.get_session = lambda u: self.store.get(u, {})
        E.save_session = self.store.__setitem__
        E.save_message = lambda *a, **k: None
        A.save_session = self.store.__setitem__
        self.E = E
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()

    def _send(self, payload):
        self.sent.append(payload)
        return True

    def tap(self, button_id):
        self.sent.clear()
        self.E.handle(self.user, self.phone, "", button_id)
        return self

    def say(self, text):
        self.sent.clear()
        self.E.handle(self.user, self.phone, text, "")
        return self

    def start(self):
        self.sent.clear()
        self.E.handle(self.user, self.phone, "", "")
        return self

    @property
    def buttons(self):
        for m in self.sent:
            if "buttons" in m:
                return [b["id"] for b in m["buttons"]]
            if "sections" in m:
                return [r["id"] for s in m["sections"] for r in s["rows"]]
        return []

    @property
    def text(self):
        return "\n".join(m.get("message", "") for m in self.sent)

    @property
    def screen(self):
        return self.store.get(self.user, {}).get("flow_screen")


# ── Flow definition ───────────────────────────────────────────────
def test_flow_definition_valid():
    """Loader startup par hi galti pakde — user ke saamne nahi."""
    from app.flow.loader import FLOW, start_screen
    assert start_screen() in FLOW["screens"]
    assert len(FLOW["screens"]) > 0


def test_no_placeholder_left_unrendered():
    """Har bheje gaye message mein {{...}} bhara hona chahiye."""
    with Bot() as bot:
        bot.start()
        assert "{{" not in bot.text


# ── Buttons ───────────────────────────────────────────────────────
def test_start_shows_welcome_buttons():
    with Bot() as bot:
        bot.start()
        assert bot.screen == "WELCOME"
        assert "CONNECT_START" in bot.buttons


def test_button_routes_without_llm():
    """Button click par LLM bilkul nahi chalna chahiye — yahi poore rebuild ka point hai."""
    with Bot() as bot, patch("app.core.llm.llm") as llm:
        bot.start().tap("SHOW_PLANS")
        assert bot.screen == "PLANS"
        assert "PLAN_BASIC" in bot.buttons
        llm.invoke.assert_not_called()


def test_unknown_button_keeps_user_in_place():
    """Anjaan payload user ko WELCOME par na pheinke — progress bach jaaye."""
    with Bot() as bot:
        bot.start().tap("SHOW_PLANS")
        bot.tap("KUCH_BHI_GALAT")
        assert bot.screen == "PLANS"


# ── Input screens ─────────────────────────────────────────────────
def test_input_screen_does_not_run_action_on_display():
    """
    Regression: ASK_BUSINESS ka action tab chale jab user likhe, dikhate waqt nahi.
    Warna CONNECT_START dabate hi 'business nahi mila' aa jaata tha.
    """
    with Bot() as bot:
        bot.start().tap("CONNECT_START")
        assert bot.screen == "ASK_BUSINESS"
        assert "nahi mila" not in bot.text


def test_text_on_input_screen_runs_search():
    with Bot() as bot, patch("app.services.google_places.search_places",
                             return_value=[FAKE_PLACE]):
        bot.start().tap("CONNECT_START").say("Sharma Sweets, Gurgaon")
        assert bot.screen == "CONFIRM_BUSINESS"
        assert "Sharma Sweets" in bot.text
        assert "BIZ_YES" in bot.buttons


def test_search_failure_goes_to_not_found():
    with Bot() as bot, patch("app.services.google_places.search_places",
                             return_value=[]):
        bot.start().tap("CONNECT_START").say("Kuch Bhi Nahi, Kahin Bhi")
        assert bot.screen == "BUSINESS_NOT_FOUND"


# ── AI fallback ───────────────────────────────────────────────────
def test_free_text_gets_ai_reply_then_buttons_return():
    class Reply:
        content = "Basic plan Rs 2,500/month hai."

    with Bot() as bot, \
         patch("app.services.google_places.search_places", return_value=[FAKE_PLACE]), \
         patch("app.ai.fallback.llm") as llm, \
         patch("app.services.knowledge_base.get_rag_context", return_value="Basic = Rs 2500"):
        llm.invoke.return_value = Reply()
        bot.start().tap("CONNECT_START").say("Sharma Sweets, Gurgaon")
        bot.say("bhai price kya hai?")

        assert "Rs 2,500" in bot.text          # AI ne jawab diya
        assert "BIZ_YES" in bot.buttons        # buttons wapas aaye
        assert bot.screen == "CONFIRM_BUSINESS"  # screen wahi rahi


def test_reshown_screen_keeps_its_params():
    """Regression: AI jawab ke baad screen dobara aaye to {{biz_name}} khaali na ho."""
    class Reply:
        content = "ji bataiye"

    with Bot() as bot, \
         patch("app.services.google_places.search_places", return_value=[FAKE_PLACE]), \
         patch("app.ai.fallback.llm") as llm, \
         patch("app.services.knowledge_base.get_rag_context", return_value=""):
        llm.invoke.return_value = Reply()
        bot.start().tap("CONNECT_START").say("Sharma Sweets, Gurgaon")
        bot.say("hmm")
        assert "Sharma Sweets" in bot.text
        assert "{{" not in bot.text


# ── Sender limits ─────────────────────────────────────────────────
def test_sender_rejects_too_many_buttons():
    from app.services.whatsapp_service import send_buttons
    with pytest.raises(ValueError, match="max 3"):
        send_buttons("9999999999", "x",
                     [{"id": str(i), "title": "B"} for i in range(4)])


def test_sender_rejects_long_button_title():
    from app.services.whatsapp_service import send_buttons
    with pytest.raises(ValueError, match="20 chars"):
        send_buttons("9999999999", "x",
                     [{"id": "a", "title": "Yeh title bahut hi lamba hai"}])


def test_phone_normalize_single_source():
    from app.services.whatsapp_service import normalize_phone
    assert normalize_phone("9876543210") == "919876543210"
    assert normalize_phone("919876543210") == "919876543210"
    assert normalize_phone("+91 98765-43210") == "919876543210"


# ── Business rules ────────────────────────────────────────────────
def test_franchise_failure_tells_truth():
    """
    Purana code fail hone par bhi 'Registration ho gaya' bolta tha aur lead
    gayab ho jaata tha. Ab sach bolna chahiye.
    """
    with Bot() as bot, patch("app.flow.actions.httpx.post",
                             side_effect=Exception("API down")):
        bot.start().tap("FRANCHISE_INFO").tap("FR_REGISTER").say("Amzad, Gurgaon")
        assert bot.screen == "FRANCHISE_FAILED"
        assert "nahi ho paaya" in bot.text
        assert not bot.store[bot.user].get("franchise_registered")


def test_support_phone_is_correct_everywhere():
    """connect.py mein 8 jagah 9283344726 tha (digit 4/5 ulte). Dobara na ho."""
    from app.core.config import SUPPORT_PHONE
    assert SUPPORT_PHONE == "9289344726"

    with Bot() as bot:
        bot.start().tap("MAIN_MENU").tap("SUPPORT")
        assert "9289344726" in bot.text
        assert "9283344726" not in bot.text


# ── Feature async delivery ────────────────────────────────────────
def _connected_bot(bot):
    bot.store[bot.user] = {
        "lang": "hi", "connect_verified": True,
        "active_location_id": "loc/1", "connected_email": "a@b.com",
        "flow_screen": "FEATURES_MENU",
    }
    return bot


def test_feature_menu_needs_connection():
    """FEATURES_MENU bina connect ke na khule — CONNECT_OFFER par bhejo."""
    with Bot() as bot:
        bot.start().tap("MAIN_MENU").tap("FREE_FEATURES")
        assert bot.screen == "CONNECT_OFFER"


def test_feature_waits_for_async_result():
    """
    Regression: trigger ke turant baad FEATURE_DONE ('aur kuch dekhna hai?')
    nahi jaana chahiye — report abhi aayi hi nahi hai.
    """
    with Bot() as bot, patch("app.services.actions_service.trigger_action",
                             return_value={"success": True}):
        _connected_bot(bot)
        bot.tap("F_QR")
        assert "tayyar kar rahi hoon" in bot.text or "Preparing" in bot.text
        assert "Aur kuch dekhna hai" not in bot.text
        assert bot.buttons == []


def test_feature_result_delivery_then_buttons():
    """Result aane par: report + phir FEATURE_DONE ke buttons."""
    from app.services import actions_service

    with Bot() as bot, patch("app.services.actions_service._claim", return_value=True):
        _connected_bot(bot)
        bot.sent.clear()
        actions_service.deliver_from_webhook(
            bot.user, bot.phone, "magic_qr",
            {"text": "Aapka QR tayyar hai!", "url": "https://x.ai/qr.png"},
        )
        assert "QR tayyar hai" in bot.text
        assert "qr.png" in bot.text
        assert "FREE_FEATURES" in bot.buttons
        assert bot.screen == "FEATURE_DONE"


def test_feature_trigger_failure_is_honest():
    with Bot() as bot, patch("app.services.actions_service.trigger_action",
                             return_value={"success": False, "message": "boom"}):
        _connected_bot(bot)
        bot.tap("F_QR")
        assert bot.screen == "FEATURE_FAILED"
        assert "9289344726" in bot.text


# ── Social connect ────────────────────────────────────────────────
def test_social_connect_sends_link_then_checks():
    with Bot() as bot:
        bot.start().tap("MAIN_MENU").tap("SOCIAL_MENU")
        assert "S_FACEBOOK" in bot.buttons

        bot.tap("S_FACEBOOK")
        assert bot.screen == "SOCIAL_PENDING"
        assert "Facebook" in bot.text
        assert "connect-business" in bot.text        # link gaya

        with patch("app.flow.actions.httpx.get") as g:
            g.return_value.status_code = 200
            g.return_value.json.return_value = {"connected": True, "pageName": "Sharma Sweets FB"}
            bot.tap("SOCIAL_CHECK")
        assert bot.screen == "SOCIAL_DONE"
        assert "Sharma Sweets FB" in bot.text


def test_social_not_connected_yet_is_honest():
    with Bot() as bot:
        bot.start().tap("MAIN_MENU").tap("SOCIAL_MENU").tap("S_INSTAGRAM")
        with patch("app.flow.actions.httpx.get") as g:
            g.return_value.status_code = 200
            g.return_value.json.return_value = {"connected": False}
            bot.tap("SOCIAL_CHECK")
        assert bot.screen == "SOCIAL_NOT_YET"
        assert "Instagram" in bot.text


# ── Demo booking (buttons se) ─────────────────────────────────────
def test_demo_booking_is_all_buttons():
    with Bot() as bot:
        bot.start().tap("MAIN_MENU").tap("BOOK_DEMO")
        assert bot.screen == "DEMO_ASK_NAME"

        bot.say("Amzad")
        assert bot.screen == "DEMO_ASK_DATE"
        assert "Amzad" in bot.text
        assert bot.buttons == ["D_TODAY", "D_TOMORROW", "D_DAYAFTER"]

        bot.tap("D_TOMORROW")
        assert bot.screen == "DEMO_ASK_TIME"
        assert bot.buttons == ["T_MORNING", "T_AFTERNOON", "T_EVENING"]

        with patch("app.flow.actions.httpx.post") as p:
            p.return_value.status_code = 200
            p.return_value.json.return_value = {"success": True}
            bot.tap("T_AFTERNOON")
        assert bot.screen == "DEMO_DONE"
        assert "3:00 PM" in bot.text


def test_demo_booking_failure_tells_truth():
    """Purana code API fail hone par bhi 'booked' bol deta tha."""
    with Bot() as bot:
        bot.start().tap("MAIN_MENU").tap("BOOK_DEMO").say("Amzad")
        bot.tap("D_TODAY")
        with patch("app.flow.actions.httpx.post", side_effect=Exception("down")):
            bot.tap("T_MORNING")
        assert bot.screen == "DEMO_FAILED"
        assert "nahi ho paaya" in bot.text
        assert not bot.store[bot.user].get("demo_booked")


def test_demo_date_is_real_and_future():
    """Purana date_extractor parse fail par 'future hai' maan leta tha."""
    from app.flow.actions import _demo_date
    from datetime import datetime
    import pytz
    today = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    for offset in (0, 1, 2):
        date_str, label = _demo_date(offset)
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        assert (d - today).days == offset
        assert label


# ── Multi-location switch ─────────────────────────────────────────
def test_location_list_and_switch():
    with Bot() as bot:
        bot.store[bot.user] = {
            "lang": "hi", "connect_verified": True,
            "connected_businesses": [
                {"title": "Sharma Sweets", "locality": "Gurgaon", "locationId": "loc/1"},
                {"title": "Sharma Sweets", "locality": "Noida", "locationId": "loc/2"},
            ],
        }
        bot.tap("SWITCH_BIZ")
        assert bot.buttons == ["LOC_0", "LOC_1"]

        bot.tap("LOC_1")
        assert bot.screen == "BIZ_SWITCHED"
        assert bot.store[bot.user]["active_location_id"] == "loc/2"


def test_location_switch_without_connection():
    with Bot() as bot:
        bot.start().tap("SWITCH_BIZ")
        assert bot.screen == "CONNECT_OFFER"


# ── Google Maps URL ───────────────────────────────────────────────
def test_maps_link_finds_business():
    with Bot() as bot, \
         patch("app.flow.actions._query_from_maps_url", return_value="Sharma Sweets Gurgaon"), \
         patch("app.services.google_places.search_places", return_value=[FAKE_PLACE]) as sp:
        bot.start().tap("CONNECT_START")
        bot.say("https://maps.app.goo.gl/abc123")
        assert bot.screen == "CONFIRM_BUSINESS"
        assert sp.call_args[0][0] == "Sharma Sweets Gurgaon"


# ── Follow-ups (Redis-backed) ─────────────────────────────────────
import time as _time


class FollowupBot(Bot):
    """Bot + asli Redis semantics (fakeredis) taaki queue sach mein test ho."""

    def __enter__(self):
        import fakeredis
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self._fp = patch("app.services.redis_service.r", self.redis)
        self._fp.start()
        super().__enter__()
        import app.services.followup_service as F
        F._r = lambda: self.redis
        self.F = F
        return self

    def __exit__(self, *a):
        self._fp.stop()
        super().__exit__(*a)

    def queue_size(self):
        return self.redis.zcard("followups")


def test_followup_scheduled_and_survives_restart():
    """
    Purana system threading.Timer use karta tha — restart par sab gayab.
    Ab queue Redis mein hai, isliye 'restart' ke baad bhi bacha rehta hai.
    """
    with FollowupBot() as bot:
        bot.store[bot.user] = {"lang": "hi", "confirmed": True, "analysis": {"score": 50}}
        bot.tap("CONNECT_GO")
        assert bot.screen == "CONNECT_PENDING"
        assert bot.queue_size() == 1          # nudge due hai

        # "restart": naya process, purani memory gayi — queue phir bhi zinda
        import importlib
        import app.services.followup_service as F
        importlib.reload(F)
        F._r = lambda: bot.redis
        assert bot.redis.zcard("followups") == 1


def test_user_reply_cancels_followup_across_workers():
    """
    Purana _active_timers per-process tha — doosre worker ka timer cancel
    nahi hota tha, aur user ko reply ke turant baad nudge milta tha.
    """
    with FollowupBot() as bot:
        bot.store[bot.user] = {"lang": "hi", "confirmed": True, "analysis": {"score": 50}}
        bot.tap("CONNECT_GO")
        assert bot.queue_size() == 1

        bot.tap("SUPPORT")           # user active ho gaya
        assert bot.queue_size() == 0  # nudge hat gaya


def test_followup_fires_when_due():
    with FollowupBot() as bot:
        bot.store[bot.user] = {"lang": "hi", "confirmed": True, "analysis": {"score": 50}}
        bot.tap("CONNECT_GO")

        # due time ko peeche khiska do
        for raw in bot.redis.zrange("followups", 0, -1):
            bot.redis.zadd("followups", {raw: _time.time() - 1})

        bot.sent.clear()
        assert bot.F.sweep_once() == 1
        assert "CONNECT_GO" in bot.buttons          # CONNECT_OFFER bheja
        assert bot.store[bot.user]["followup_count"] == 1


def test_followup_not_sent_if_work_already_done():
    """Connect ho chuka to 'connect karlo' wala nudge mat bhejo."""
    with FollowupBot() as bot:
        bot.store[bot.user] = {"lang": "hi", "confirmed": True, "analysis": {"score": 50}}
        bot.tap("CONNECT_GO")
        for raw in bot.redis.zrange("followups", 0, -1):
            bot.redis.zadd("followups", {raw: _time.time() - 1})

        bot.store[bot.user]["connect_verified"] = True   # ab connect ho gaya
        bot.sent.clear()
        bot.F.sweep_once()
        assert bot.sent == []


def test_only_one_worker_sends_each_followup():
    """ZREM atomic hai — do worker ek saath sweep karein to bhi ek hi bhejega."""
    with FollowupBot() as bot:
        bot.store[bot.user] = {"lang": "hi", "confirmed": True, "analysis": {"score": 50}}
        bot.tap("CONNECT_GO")
        for raw in bot.redis.zrange("followups", 0, -1):
            bot.redis.zadd("followups", {raw: _time.time() - 1})

        assert bot.F.sweep_once() == 1   # worker 1
        assert bot.F.sweep_once() == 0   # worker 2 ko kuch nahi mila
