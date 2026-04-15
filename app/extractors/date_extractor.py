import dateparser
from datetime import datetime, timedelta
import pytz
from app.core.config import TIMEZONE


def parse_datetime(text: str) -> dict:
    """
    Parse natural language date/time (Hindi/English/Hinglish).
    Returns: {status, parsed_date, parsed_time, display, message}
    """
    ist = pytz.timezone(TIMEZONE)
    now = datetime.now(ist)

    settings = {
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "TIMEZONE": TIMEZONE,
        "TO_TIMEZONE": TIMEZONE,
    }

    parsed = dateparser.parse(text, languages=["hi", "en"], settings=settings)

    if not parsed:
        return {
            "status": "error",
            "message": "Date/time samajh nahi aayi. Please clearly batayein, jaise: 'kal 3 baje' ya '15 April 2 PM'"
        }

    if parsed < now:
        suggested = now + timedelta(hours=2)
        return {
            "status": "past",
            "message": f"Yeh time already guzar chuka hai. Kya {suggested.strftime('%d %B, %I:%M %p')} theek rahega?"
        }

    return {
        "status": "ok",
        "parsed_date": parsed.strftime("%Y-%m-%d"),
        "parsed_time": parsed.strftime("%I:%M %p"),
        "display": parsed.strftime("%d %B %Y, %I:%M %p"),
        "message": "ok"
    }


def is_future_datetime(date_str: str, time_str: str) -> bool:
    """Check if given date+time is in the future"""
    try:
        ist = pytz.timezone(TIMEZONE)
        now = datetime.now(ist)
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")
        dt = ist.localize(dt)
        return dt > now
    except Exception:
        return True  # Default to True if can't parse