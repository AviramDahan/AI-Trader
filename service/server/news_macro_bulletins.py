"""Compare reported CPI/PPI figures across the two observed relay formats."""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import re


COUNTRIES = {"japan": "יפן", "germany": "גרמניה"}
INDICATORS = {"CPI": "מדד המחירים לצרכן", "PPI": "מדד מחירי היצרן",
              "EU HARMONISED CPI": "מדד המחירים לצרכן המתואם לאיחוד האירופי"}
MONTHS = dict(zip(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(),
    "ינואר פברואר מרץ אפריל מאי יוני יולי אוגוסט ספטמבר אוקטובר נובמבר דצמבר".split(),
))
COUNTRY = r"(?P<country>Japan(?:ese)?|German(?:y)?)"
METRIC = r"(?P<indicator>(?:EU Harmonised )?CPI|PPI)"
NUMBER = r"[+-]?\d{1,4}(?:\.\d{1,4})?"
VALUES = rf"(?P<actual>{NUMBER})%\s*\((?:forecast|est)\s+(?P<forecast>{NUMBER})%[,;]\s*(?:previous|prev)\s+(?P<previous>{NUMBER})%\)"
RELAY = re.compile(
    rf"(?:❗\ufe0f?\s*)?{COUNTRY}\s+{METRIC}\s+(?:(?P<stage>FINAL|FLASH)\s+)?"
    rf"(?P<interval>MOM|YOY)\s+ACTUAL\s+{VALUES}(?:\s+\$MACRO\|FJ)?", re.I)
WIRE = re.compile(
    rf"(?:-\s*)?(?:{COUNTRY}\s+)?{METRIC}\s*\((?P<interval>M/M|Y/Y)\)"
    rf"(?:\s+(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))?"
    rf"(?:\s+(?P<stage>F|P))?\s*:\s*{VALUES}", re.I)
WINDOW = timedelta(minutes=10)


@dataclass(frozen=True)
class Release:
    country: str
    indicator: str
    interval: str
    stage: str
    month: str
    values: tuple[Decimal, Decimal, Decimal]

    def same_figure(self, other):
        return ((self.country, self.indicator, self.interval, self.stage, self.values)
                == (other.country, other.indicator, other.interval, other.stage, other.values)
                and (not self.month or not other.month or self.month == other.month))


def _parse_line(line, first=None):
    match = RELAY.fullmatch(line) or WIRE.fullmatch(line)
    if match is None:
        return None
    fields = match.groupdict()
    name = (fields["country"] or "").lower()
    country = ("japan" if name.startswith("japan") else "germany") if name else first.country if first else ""
    if not country:
        return None
    stage = {"F": "final", "FINAL": "final", "P": "preliminary", "FLASH": "preliminary"}.get(
        (fields["stage"] or "").upper(), first.stage if first else "")
    month = (fields.get("month") or (first.month if first else "")).lower()
    return Release(country, fields["indicator"].upper(), fields["interval"].upper().replace("/", "O"),
                   stage, month, tuple(Decimal(fields[k]) for k in ("actual", "forecast", "previous")))


def releases(title, excerpt):
    """Return figures only when every content line is understood."""
    first = _parse_line(" ".join(str(title or "").split()))
    if first is None:
        return ()
    facts = [first]
    lines = [" ".join(line.split()) for line in str(excerpt or "").splitlines() if line.strip()]
    if len(lines) > 12:
        return ()
    for line in lines:
        if re.fullmatch(r"\(@[A-Za-z0-9_]+\)", line):
            continue
        fact = _parse_line(line, first)
        if fact is None:
            return ()
        if fact not in facts:
            facts.append(fact)
    return tuple(facts)


def unpublished_figures(cur, row, facts, published_at):
    """Compare exact, version-bound receipts in the existing market alert ledger."""
    from news_pipeline import _loads, _z

    previous = cur.execute("""
        SELECT seen.title,seen.source_facts_json,o.message FROM scanner_news_broadcast_alerts a
        JOIN scanner_news seen ON seen.id=a.news_id
        JOIN scanner_telegram_outbox o
          ON o.dedupe_key=('market-news:' || CAST(seen.id AS TEXT) || ':' || a.event_version)
        WHERE a.channel='market' AND seen.id<>? AND seen.provider='telegram_channels'
          AND seen.published_at BETWEEN ? AND ?
          AND seen.content_hash=a.event_version
          AND o.status IN ('pending','retry','sending','sent')
        ORDER BY seen.published_at DESC LIMIT 100
    """, (row["id"], _z(published_at - WINDOW), _z(published_at + WINDOW))).fetchall()
    seen = []
    for prior in previous:
        source = _loads(prior["source_facts_json"], {})
        if isinstance(source, dict):
            facts_in_source = releases(prior["title"], source.get("source_excerpt"))
            for fact in facts_in_source:
                message = prior["message"]
                if message.startswith(tuple(f"📰 {name} · " for name in COUNTRIES.values())):
                    # Presentation may add a priority line under the heading.
                    body = '\n'.join(line for line in message.splitlines() if not line.startswith('חשיבות '))
                    if render((fact,)) not in body:
                        continue  # The previous notice may have contained only the new figures.
                seen.append(fact)
    return tuple(fact for fact in facts if not any(fact.same_figure(item) for item in seen))


def render(facts):
    output = []
    for fact in facts:
        frequency = "חודשי" if fact.interval == "MOM" else "שנתי"
        stage = {"final": " · סופי", "preliminary": " · ראשוני"}.get(fact.stage, "")
        period = " · " + MONTHS[fact.month] if fact.month else ""
        actual, forecast, previous = [format(value.normalize(), "f") for value in fact.values]
        output.append(f"📰 {COUNTRIES[fact.country]} · {INDICATORS[fact.indicator]} ({fact.indicator}) · "
                      f"{frequency}{stage}{period}\nבפועל {actual}% · צפי {forecast}% · קודם {previous}%")
    return "\n\n".join(output)
