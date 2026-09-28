"""Public-news presentation only; never modify stored evidence or AI inputs."""
import re


def hide_relay_branding(value):
    # Model output can put invisible RTL/LTR controls between Telegram and @.
    # Normalize presentation before matching; evidence remains untouched.
    value=re.sub(r'[\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]', '', value)
    relay=r'(?:(?:Telegram|(?:ה)?טלגרם)\s*[:：]?\s*@[A-Za-z0-9_]+|(?:Telegram|טלגרם)\s+Financial\s*Juice)'
    # Replace the whole wrapper, not just the handle (which leaves broken Hebrew).
    value=re.sub(r'(?:לפי|על[־ ]פי)\s+(?:(?:כותרת|דיווח|הודעה|פוסט)\s+(?:שפרסם|שפרסמה|שפורסם|שפורסמה)\s+)?(?:ב?ערוץ\s+)?'+relay+r'\s*,?', 'לפי דיווח,', value, flags=re.I)
    # Standalone collection provenance, not the actual reported statement.
    value=re.sub(r'(?:הדברים|המידע|הדיווח|הידיעה)\s+(?:דווחו|פורסמו|פורסם|פורסמה|דווח|דווחה)\s+(?:ב)?ערוץ\s+'+relay+r'\s*[.]?', '', value, flags=re.I)
    # Keep the assertion attributed/uncertain, without promoting its relay.
    value=re.sub(r'(?:לפי|על פי)\s+(?:ערוץ\s+)?'+relay+r'\s*,?', 'לפי דיווח,', value, flags=re.I)
    lines=[]
    for line in value.splitlines():
        if re.fullmatch(r'\s*(?:מקור:\s*)?(?:ערוץ\s+)?'+relay+r'[\s:.]*',line,re.I):continue
        line=re.sub(r'(?:ערוץ\s+)?'+relay,'דיווח',line,flags=re.I)
        line=re.sub(r'\s*\|\s*FJ\b','',line,flags=re.I)
        lines.append(re.sub(r'[ \t]{2,}',' ',line).strip())
    return re.sub(r'\n{3,}','\n\n','\n'.join(lines)).strip()
