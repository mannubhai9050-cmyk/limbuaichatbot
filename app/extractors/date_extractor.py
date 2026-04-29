from datetime import datetime
import pytz
from app.core.config import TIMEZONE


def is_future_datetime(date_str: str, time_str: str) -> bool:
    try:
        ist = pytz.timezone(TIMEZONE)
        now = datetime.now(ist)
        dt_str = f"{date_str} {time_str}"
        for fmt in ["%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"]:
            try:
                dt = datetime.strptime(dt_str, fmt)
                dt_ist = ist.localize(dt)
                return dt_ist > now
            except ValueError:
                continue
        return True  # If parse fails, assume future
    except Exception:
        return True