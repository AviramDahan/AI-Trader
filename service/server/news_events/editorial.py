"""Conservative public-news editorial helpers. No I/O or trading decisions.

Release identity is not headline similarity. Only a complete, explicitly dated
period CPI bulletin supplies this additional anchor. Unknown prose stays on the
existing evidence/review path, never guessed into a release or thrown away.
"""
import re


COUNTRIES = ('New Zealand', 'Australia', 'United States', 'United Kingdom',
             'Canada', 'Japan', 'China', 'Germany', 'France', 'Eurozone')
NUMBER = r'[+-]?\d{1,3}(?:\.\d{1,4})?'
PERIOD = r'(?:Q[1-4]|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)(?: 20\d{2})?'
BULLETIN = re.compile(
    r'(?P<country>'+'|'.join(COUNTRIES)+r') (?P<series>(?:Core )?CPI) '
    r'\((?P<frequency>Q/Q|Y/Y|M/M)\) (?P<period>'+PERIOD+r'): '
    r'(?P<actual>'+NUMBER+r')% \((?:est|forecast) (?P<forecast>'+NUMBER+r')%; '
    r'(?:prev|previous) (?P<previous>'+NUMBER+r')%\)', re.I)
MONTHS = {name[:3].lower():i for i,name in enumerate(
    ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'),1)}


def macro_release(source):
    """Return (exact release key, grounded claims), or None. Never infer year.

    Publication day separates release occurrences; it is NOT the reported period.
    Monthly and quarterly periods cannot share an anchor. Headline must fully
    match; an optional complete excerpt bulletin can add an annual component.
    Free-text excerpts are retained by Store but do not prove material change.
    """
    from .model import text, timestamp, fingerprint
    if (source.get('event_type')!='market' or source.get('cik')
            or source.get('tickers') or source.get('rights')!='approved'):
        return None
    title=text(source.get('title'))
    match=BULLETIN.fullmatch(title)
    if not match:return None

    def identity(m):
        period=m['period'].lower().split()
        part=period[0]
        quarter=part.startswith('q')
        if m['frequency'].upper()=='Q/Q' and not quarter:return None
        if m['frequency'].upper()=='M/M' and quarter:return None
        token=part if quarter else 'm'+str(MONTHS[part[:3]])
        # Unknown reported year is explicit, never filled from publication time.
        return (m['country'].casefold(),m['series'].casefold(),token,
                period[1] if len(period)>1 else 'year_unspecified',
                timestamp(source['published_at'])[:10])

    key=identity(match)
    if key is None:return None
    claims={}
    packets=[match]
    extra=BULLETIN.fullmatch(text(source.get('source_excerpt')))
    if extra and identity(extra)==key:packets.append(extra)
    for packet in packets:
        for field in ('actual','forecast','previous'):
            claim='macro_release:'+fingerprint([key,packet['frequency'].upper(),field])
            if claim in claims and claims[claim]['value']!=packet[field]:
                # A contradictory headline/body is not a trusted bulletin.
                # Retain it on the existing attributed quality-review path.
                return None
            claims[claim]={'value':packet[field], 'quote':packet.group(0)}
    return 'macro_release:'+fingerprint(key),claims


def priority(event, personal):
    """Bounded queue preference, not an impact score or publication permission.

    Existing position/watch priority is first. Concrete reported events precede
    generic updates within the current oldest-20 window; stable sort retains age
    ties. No extra AI calls, new queue or ticker/provider preference.
    """
    from .macro_rules import factual_macro_title
    kind=event.get('event_type')
    concrete=(kind in {'earnings','guidance','merger','financing','cybersecurity',
                      'clinical','restructuring','litigation','regulatory'}
              or (kind=='market' and (factual_macro_title(event.get('title',''))
                  or any(macro_release(s) for s in event.get('sources',[])))))
    return (not bool(set(event.get('tickers',[])) & set(personal)),not concrete)
