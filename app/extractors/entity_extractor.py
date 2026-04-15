import re


def extract_phone(text: str) -> str | None:
    """Extract 10-digit Indian phone number"""
    patterns = [
        r'\b[6-9]\d{9}\b',
        r'\b(\+91|91)[-\s]?([6-9]\d{9})\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            phone = re.sub(r'[^\d]', '', match.group())
            if phone.startswith('91') and len(phone) == 12:
                phone = phone[2:]
            if len(phone) == 10:
                return phone
    return None


def extract_email(text: str) -> str | None:
    """Extract email address"""
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return match.group() if match else None


def extract_name(text: str) -> str | None:
    """Basic name extraction — looks for capitalized words after name indicators"""
    patterns = [
        r'(?:mera naam|my name is|main hoon|i am|naam hai)\s+([A-Za-z\s]{2,30})',
        r'(?:name:|naam:)\s*([A-Za-z\s]{2,30})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def extract_action_params(text: str) -> dict:
    """Parse key=value|key=value format from action tags"""
    params = {}
    for part in text.strip().split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip()] = v.strip()
    return params