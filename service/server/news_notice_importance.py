"""Editorial explanation based on retained facts."""
from decimal import Decimal
import re

from telegram_presentation import telegram_text, utf16_length


def _line(level, reason):
    return f'חשיבות {level} · {reason}'


def _headline(title):
    if not isinstance(title, str) or len(title) > 600:
        return ''
    return ' '.join(title.partition('\n')[0].split())


def analyst_importance(title, excerpt=''):
    from news_analyst_routing import is_analyst_update

    title = _headline(title)
    if (not is_analyst_update(title, excerpt)
            or re.search(r'\b(?:upgrad\w*|downgrad\w*)\s+(?:its |their )?(?:cloud|software|platform|hardware)\b', title, re.I)):
        return _line('לא נקבעה', 'פעולת אנליסט לא הובהרה בכותרת')
    if re.search(r'\b(?:upgrad\w*|downgrad\w*)\b|שדרג|הוריד.{0,20}המלצ|העל.{0,20}המלצ', title, re.I):
        return _line('בינונית', 'חל שינוי בדירוג המניה')
    target = re.search(r'\b(?:price[ -]target|PT)\b.{0,50}?\bto\s+((?:US|C|A)?[$€£])\s*(\d[\d,]*(?:\.\d+)?)\s+'
                       r'from\s+((?:US|C|A)?[$€£])\s*(\d[\d,]*(?:\.\d+)?)', title, re.I)
    if target and target[1].upper() == target[3].upper():
        new, old = (Decimal(target[i].replace(',', '')) for i in (2, 4))
        if new > 0 and old > 0 and new != old:
            change = 100 * abs(new - old) / old
            shown = f'{change:.1f}'.removesuffix('.0')
            if shown == '0':
                shown = 'פחות מ־0.1'
            else:
                shown = f'כ־{shown}'
            direction = 'עלה' if new > old else 'ירד'
            return _line('בינונית' if change >= 10 else 'נמוכה',
                         f'מחיר היעד {direction} ב{shown}% ביחס ליעד הקודם')
    if re.search(r'\binitiat\w*\s+(?:research\s+)?coverage\b|החל.{0,15}לסקר', title, re.I):
        return _line('נמוכה', 'החל סיקור של המניה')
    return _line('לא נקבעה', 'עדכון אנליסט ללא שיעור שינוי בר־השוואה')


def macro_importance(values):
    deltas = [actual - forecast for actual, forecast in values]
    if not deltas:
        return _line('לא נקבעה', 'אין צפי בר־השוואה')
    if len(deltas) == 1 and deltas[0]:
        delta = deltas[0]
        direction = 'מעל הצפי' if delta > 0 else 'מתחת לצפי'
        return _line('בינונית', f'בפועל {abs(delta).normalize():f} נקודות אחוז {direction}')
    if any(deltas):
        return _line('בינונית', 'נרשם פער מול הצפי באחד או יותר מהנתונים')
    return _line('נמוכה', 'ללא הפתעה מול הצפי בנתונים המוצגים')


EVENTS = (
    ('גבוהה', 'החברה שינתה או משכה את התחזית שלה',
     r'\b(?:raises?|cuts?|lowers?|lifts?|withdraws?|suspends?)\s+'
     r'(?:(?:its|full[- ]year|quarterly|annual|Q[1-4]|FY(?:\d{2,4})?|(?:20)?\d{2}|adjusted|sales|revenue|EPS|earnings|profit|margin)\s+){0,7}'
     r'(?:guidance|outlook)\b'),
    ('גבוהה', 'דווחה החלטה רגולטורית קונקרטית',
     r'^\W*(?:FDA|EMA|FTC|DOJ)\s+(?:approves?|rejects?|blocks?|clears?)\b'),
    ('גבוהה', 'דווח על הסכם רכישה או מיזוג',
     r'\b(?:agrees? to (?:acquire|merge with)|signs? (?:an? )?(?:definitive )?merger agreement)\b'),
    ('גבוהה', 'הוגשה בקשה להליך פשיטת רגל',
     r'\bfiles? for (?:chapter 11|bankruptcy)\b'),
    ('בינונית', 'החברה דיווחה על אירוע סייבר',
     r'\b(?:reports?|discloses?|confirms?)\b.{0,38}\b(?:data breach|cyberattack)\b'),
    ('לא נקבעה', 'פורסם נתון כלכלי. הפער מול הצפי טרם נקבע',
     r'\b(?:CPI|PPI|PCE|GDP|payrolls?|jobless claims|unemployment|retail sales)\b.{0,95}\d'),
    ('נמוכה', 'הידיעה מתארת בעיקר תנועת מחיר',
     r'^(?:(?:the )?(?:S&P 500|Nasdaq|Dow|oil|gold|Treasury yields?)|[\w. -]{1,40} (?:shares|stock))\s+'
     r'(?:rise\w*|fall\w*|jumps?|drops?|surges?|up|down)\b.{0,25}\d'),
)


_COUNTRY = r'(?:US|U\.S\.|United States|Eurozone|France|French|German(?:y)?|Japan(?:ese)?|Spain|Spanish|Switzerland|Swiss|Canada|Canadian|UK|United Kingdom)'
_INFLATION = rf'{_COUNTRY}\s+(?:(?:EU Harmoni[sz]ed|Core)\s+)?(?:CPI|PPI)\s+'
_PCT = r'[+-]?\d{1,3}(?:\.\d{1,4})?'
_COMPARISON = rf'(?P<actual>{_PCT})%\s*\((?:forecast|est)\s+(?P<forecast>{_PCT})%\s*[,;]\s*(?:previous|prev)\s+{_PCT}%\)'
_INFLATION_RELEASE = re.compile(
    rf'(?:[‼❗]\ufe0f?\s*)?{_INFLATION}(?:'
    r'(?:FINAL |FLASH |NSA )?(?:MOM|YOY|MM|YY)(?: (?:FINAL|FLASH|NSA))? ACTUAL\s+|'
    r'\((?:M/M|Y/Y)\)(?: [A-Za-z]{3,9})?(?: [FP])?:\s*)'
    + _COMPARISON + r'(?:\s+\$MACRO(?:\|FJ)?)?', re.I,
)


def _inflation_forecast(title):
    # This is a presentation-only fallback for complete headlines outside the
    # existing cross-feed dedupe parser's countries. It assigns no release ID.
    match = _INFLATION_RELEASE.fullmatch(title)
    return (Decimal(match['actual']), Decimal(match['forecast'])) if match else None


def news_importance(title, excerpt='', *, report=False, analyst=False):
    from news_events.macro_rules import reported_market_movement, reported_rate_decision
    from news_report_routing import has_reported_results, has_financial_values

    title = _headline(title)
    if report:
        return _line('בינונית', 'פורסמו תוצאות בפועל. בדקו את הצפי וההשוואה בהודעה')
    if analyst:
        return analyst_importance(title, excerpt)
    if (not title or '?' in title or re.search(
            r'\b(?:could|might|may|would|rumou?rs?|reportedly|preview|denies?|false|not|expected|expects? to|if)\b'
            r'|ייתכן|שמועה|לקראת', title, re.I)):
        return _line('לא נקבעה', 'לא הוצג שינוי מהותי שאפשר לסווג מהמידע הקיים')
    if reported_rate_decision(title) or re.fullmatch(
            r'(?:Fed|Federal Reserve|ECB) (?:holds|keeps|raises|cuts) interest rates (?:at|to) [+-]?\d+(?:\.\d+)?%', title, re.I):
        return _line('גבוהה', 'החלטת ריבית של בנק מרכזי')
    if forecast := _inflation_forecast(title):
        return macro_importance([forecast])
    for level, reason, pattern in EVENTS:
        if re.search(pattern, title, re.I):
            return _line(level, reason)
    if reported_market_movement(title):
        return _line('נמוכה', 'עדכון על תנועת השוק')
    if has_reported_results(title, excerpt) and has_financial_values(title, excerpt):
        return _line('בינונית', 'פורסמו תוצאות כספיות לתקופה מוגדרת')
    return _line('לא נקבעה', 'לא הוצג שינוי מהותי שאפשר לסווג מהמידע הקיים')


def add_importance(message, annotation, *, limit=3500):
    """Keep the original heading and omit the annotation if it would clip text."""
    heading, separator, body = message.partition('\n')
    if not heading.strip() or body.startswith(('חשיבות ', 'מידע למעקב ·')):
        return message
    updated = heading + '\n' + annotation + separator + body
    if utf16_length(telegram_text(updated, limit=100_000)) > limit:
        return message
    return updated


SEC_IMPORTANCE = {
    'company_report': _line('בינונית', 'תוצאות בפועל לתקופה מדווחת. השוואה לשנה קודמת אינה צפי'),
    'sec_intelligence': _line('לא נקבעה', 'דיווח SEC. בדקו מה השתנה בפועל'),
    'ownership_activity': 'מידע למעקב · עסקה או החזקה דווחה. היקף מדווח מופיע בהודעה',
    'buyback_activity': _line('בינונית', 'דווח על תשלום בפועל לרכישה עצמית בתקופה המצוינת'),
}
TRUMP_IMPORTANCE = _line('לא נקבעה', 'התוכן המיוחס לטראמפ טרם אומת')
