import { useEffect, useState } from 'react'
import { API_ORIGIN } from './appShared'

type Row = Record<string, any>
const value = (v: any, suffix = '') => v != null && Number.isFinite(Number(v)) ? `${Number(v).toFixed(2)}${suffix}` : '—'
const reasonNames: Record<string, string> = {
  pre_no_fresh_quote: 'אין מחיר ייחוס טרי', no_fresh_intraday_quote_or_market_closed: 'אין מחיר תוך־יומי טרי / שוק סגור',
  pre_no_forward_zone: 'אין אזור התנגדות קדמי', pre_nearest_resistance_below_2r: 'ההתנגדות הקרובה לפני 2R',
  pre_entry_inside_unresolved_price_zone: 'הכניסה בתוך אזור לא פתור', pre_invalid_rounded_levels: 'רמות לא תקינות אחרי עיגול',
  pre_no_structural_stop_anchor: 'אין עוגן סטופ מבני', pre_structural_stop_too_distant: 'הסטופ המבני רחוק מדי',
  insufficient_current_news: 'אין די חדשות עדכניות', news_provider_unavailable_fail_closed: 'נתוני החדשות אינם זמינים',
  ai_or_confidence_filter: 'החלטת AI / ציון / רלוונטיות לא עברו', news_sentiment_conflict: 'סתירה בכיוון החדשות',
  pre_duplicate_cooldown: 'המתנה אחרי סיגנל קודם', duplicate_cooldown: 'המתנה אחרי סיגנל קודם',
}
const reasonText = (reason: string, he: boolean) => he ? reasonNames[reason] || reason : reason
const stageNames: Record<string, string> = { quote: 'נתוני מחיר', news: 'חדשות', targets: 'מבנה / יעד / RR', ai_filter: 'סינון AI', cooldown: 'המתנה', other: 'אחר / חסרה ראיה' }

function Levels({ check, he }: { check: Row, he: boolean }) {
  const g = check.geometry || {}, accepted = check.accepted_levels || {}
  const levels: [string, any, string][] = [
    [he ? 'כניסה בבדיקה' : 'Reference entry', check.quote?.price, '#eab308'],
    [he ? 'סטופ שנבדק' : 'Checked stop', accepted.stop ?? g.stop_rounded, '#fb7185'],
    [accepted.active_target != null ? (he ? 'יעד בתוכנית' : 'Plan target') : (he ? 'יעד שנבדק' : 'Checked target'), accepted.active_target ?? g.target_rounded, '#34d399'],
    [he ? 'התנגדות קרובה' : 'Nearest resistance', g.nearest_resistance?.low, '#a78bfa'],
  ]
  const available = levels.filter(([, n]) => n != null && Number.isFinite(Number(n)))
  if (available.length < 2) return <p>{he ? 'חסרות רמות להצגת המבנה.' : 'Not enough retained levels to display structure.'}</p>
  const prices = available.map(([, n]) => Number(n)), lo = Math.min(...prices), hi = Math.max(...prices)
  const x = (n: number) => 145 + (n - lo) / Math.max(hi - lo, .01) * 125
  return <figure className="research-level-chart" dir="ltr">
    <svg viewBox="0 0 380 180" role="img" aria-label={he ? 'רמות שנשמרו בזמן ההחלטה' : 'Decision-time saved levels'}>
      {available.map(([label, n, color], index) => <g key={label}>
        <line x1={145} x2={270} y1={35 + index * 38} y2={35 + index * 38} stroke="currentColor" opacity=".15" />
        <circle cx={x(Number(n))} cy={35 + index * 38} r="5" fill={color} />
        <text x={he ? 125 : 8} textAnchor={he ? 'end' : 'start'} y={39 + index * 38} fill="currentColor" fontSize="12">{label}</text>
        <text x="300" y={39 + index * 38} fill={color} fontSize="13">{value(n)}</text>
      </g>)}
    </svg>
    <figcaption>{he ? 'רמות בזמן ההחלטה בלבד; אין כאן נרות משוחזרים או כניסה שבוצעה.' : 'Decision-time levels only; no reconstructed candles or asserted fill.'}</figcaption>
  </figure>
}

function Candidate({ row, he }: { row: Row, he: boolean }) {
  const stamp = (s: string) => s ? new Date(s).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  return <details className="research-candidate">
    <summary><bdi>{row.ticker}</bdi> · <bdi>{row.company || '—'}</bdi> · <bdi>{row.direction || '—'}</bdi><br />
      <small>{stamp(row.at)} · {row.rejection ? reasonText(row.rejection, he) : row.signals.length ? (he ? 'סיגנל נשמר' : 'Signal saved') : (he ? 'אין תוצאה סופית מתועדת' : 'No retained final result')}</small>
    </summary>
    <p>{he ? 'חלון מסחר בזמן הבדיקה' : 'Session at check'}: {row.session?.is_open ? (he ? 'פתוח' : 'Open') : row.session?.reason || '—'} · {he ? 'ניסיונות AI מתועדים' : 'Recorded AI attempts'}: {row.ai_attempts}</p>
    <ol className="research-timeline">
      <li>{he ? 'סינון טכני' : 'Technical'}: {row.technical_recorded ? (he ? 'מועמד מתועד' : 'Candidate recorded') : (he ? 'לא זמין' : 'Unavailable')}</li>
      {row.target_checks.map((check: Row, i: number) => <li key={i}>
        <bdi>{check.phase} · {check.outcome} · {check.policy_version}</bdi> · {stamp(check.decided_at || check.observed_at)}
        {check.rejection_reason && <p>{reasonText(`pre_${check.rejection_reason.replace(/^pre_/, '')}`, he)} <bdi>({check.rejection_reason})</bdi></p>}
        <dl className="research-levels">
          <div><dt>{he ? 'מחיר ייחוס' : 'Reference price'}</dt><dd><bdi>{value(check.quote?.price)}</bdi></dd></div>
          <div><dt>{he ? 'זמן המחיר' : 'Quote timestamp'}</dt><dd>{stamp(check.quote?.as_of)}</dd></div>
          <div><dt>{he ? 'מועד נתוני המבנה' : 'Structure data as of'}</dt><dd><bdi>{check.source_inputs?.data_as_of || '—'}</bdi></dd></div>
          <div><dt>RR {he ? 'ברוטו אחרי עיגול' : 'gross after rounding'}</dt><dd><bdi>{value(check.accepted_levels?.rr?.[0] ?? check.geometry?.rr_rounded, 'R')}</bdi></dd></div>
        </dl>
        <Levels check={check} he={he} />
        {!!check.rejection_detail?.length && <p><bdi>{check.rejection_detail.join(', ')}</bdi></p>}
        {!!check.source_inputs?.zones?.length && <details><summary>{he ? 'אזורי המבנה וראיות האישור שנשמרו' : 'Saved structure zones and confirmation evidence'}</summary>
          {check.source_inputs.zones.map((zone: Row, index: number) => <p key={index}><bdi>{value(zone.low)}–{value(zone.high)}</bdi> · {he ? 'מגעים' : 'Touches'}: {zone.touches ?? '—'}<br />
            {(zone.pivots || []).map((p: Row, j: number) => <span key={j}><bdi>{p.kind} · {p.date}</bdi> · {he ? 'אושר' : 'Confirmed'}: {stamp(p.confirmed_at)}<br /></span>)}</p>)}
        </details>}
        {check.evidence_gap && <p className="scanner-warning">{he ? 'ראיות המבנה אינן מלאות' : 'Incomplete structure evidence'}: <bdi>{check.evidence_gap}</bdi></p>}
      </li>)}
      {row.reviews.map((review: Row, i: number) => <li key={`ai${i}`}>AI · <bdi>{review.result}</bdi> · {review.attempts} {he ? 'ניסיונות' : 'attempts'}{review.rejection && <> · {reasonText(review.rejection, he)}</>}</li>)}
      {row.signals.map((s: Row) => <li key={s.id}>{he ? 'זכאות סיגנל: אושר; ביצוע דמה' : 'Signal qualified; paper execution'}: <bdi>{s.status}</bdi> · {he ? 'כניסה בפועל' : 'Actual entry'}: <bdi>{value(s.actual_entry)}</bdi> · {he ? 'תוקף' : 'Valid until'}: {stamp(s.valid_until)}</li>)}
      {row.orders.map((o: Row) => <li key={`order${o.id}`}>{he ? 'פקודה' : 'Order'} <bdi>#{o.id} · {o.purpose} · {o.status}</bdi></li>)}
    </ol>
    <small>{he ? 'חוסר מזומן/הקצאה אינו פסילת איכות; כניסה מופעלת רק לאחר fill תקף. שלב שאינו מתועד אינו נחשב שעבר.' : 'Allocation is separate from signal quality; a position activates only after a valid fill. Unrecorded stages are not assumed to pass.'}</small>
  </details>
}

export function SignalResearch({ he, mode = 'research' }: { he: boolean, mode?: 'research' | 'summary' | 'results' }) {
  const [hours, setHours] = useState(48)
  const [data, setData] = useState<Row | null>(null)
  const [error, setError] = useState('')
  const [side, setSide] = useState('all')
  const [ticker, setTicker] = useState('')
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    let inFlight = false
    setData(null)
    const refresh = async () => {
      if (inFlight) return
      inFlight = true
      try {
        const r = await fetch(`${API_ORIGIN}/api/scanner/research?hours=${hours}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]), cache: 'no-store' })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const result = await r.json()
        if (active) { setData(result); setError('') }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : 'Unavailable') }
      finally { inFlight = false }
    }
    void refresh()
    const interval = window.setInterval(() => void refresh(), 60000)
    return () => { active = false; controller.abort(); window.clearInterval(interval) }
  }, [hours])
  return <ResearchView he={he} mode={mode} data={data} error={error} hours={hours} setHours={setHours} side={side} setSide={setSide} ticker={ticker} setTicker={setTicker} />
}

export function ResearchView({ he, mode = 'research', data, error = '', hours = 48,
  setHours = () => {}, side = 'all', setSide = () => {}, ticker = '', setTicker = () => {} }: {
  he: boolean, mode?: 'research' | 'summary' | 'results', data: Row | null, error?: string, hours?: number,
  setHours?: (hours: number) => void, side?: string, setSide?: (side: string) => void,
  ticker?: string, setTicker?: (ticker: string) => void,
}) {
  const t = (a: string, b: string) => he ? a : b
  const stamp = (s: string) => s ? new Date(s).toLocaleString(he ? 'he-IL' : 'en-GB') : t('לא זמין', 'Unavailable')
  const counts = data?.counts || {}
  const reasons = Object.entries(data?.rejection_reasons || {}).sort((a: any, b: any) => b[1] - a[1])
  const filtered = (data?.records || []).filter((r: Row) => (!ticker || r.ticker.includes(ticker.toUpperCase())) && (side === 'all' || r.direction === side))
  return <section className="scanner-section signal-research" aria-label={t('מחקר סיגנלים', 'Signal research')}>
    <header className="research-header"><h2>{mode === 'results' ? t('איכות תוצאות הסיגנלים', 'Signal outcome quality') : t('מחקר סיגנלים — למה אין סיגנל?', 'Signal research — why no signal?')}</h2>
      <label>{t('חלון', 'Window')} <select value={hours} onChange={e => setHours(Number(e.target.value))}><option value={24}>24h</option><option value={48}>48h</option><option value={168}>7 {t('ימים', 'days')}</option></select></label></header>
    {error && <p role="alert" className="scanner-inline-error">{t('נתוני המחקר אינם זמינים כרגע', 'Research data unavailable')}: {error}</p>}
    {!data && !error && <p role="status">{t('טוען ראיות שמורות…', 'Loading retained evidence…')}</p>}
    {data && <>
      <p className="scanner-note">{stamp(data.window_since)} – {stamp(data.generated_at)} · {t('ראיות יעדים זמינות מאז', 'Target evidence available since')}: {stamp(data.available_since)}</p>
      {!!data.clipped.length && <p className="scanner-warning">{t('חלק מפרטי המדגם מוגבלים. סך בדיקות המועמד והסימולים מחושב לכל החלון; שאר המדדים מתייחסים למדגם שנקרא.', 'Some detail sources are capped. Candidate-observation and ticker totals cover the full window; other metrics use the bounded sample.')} <bdi>{data.clipped.join(', ')}</bdi></p>}
      {mode !== 'results' && <>
        <div className="scanner-stage-grid">{[
          [t('בדיקות מועמד', 'Candidate observations'), counts.candidate_observations], [t('סימולים ייחודיים', 'Unique tickers'), counts.unique_tickers],
          [t('עברו יעד לפני AI', 'Pre-AI target passes'), counts.target_pass], [t('מועמדים עם ניסיון AI', 'AI attempted candidates'), counts.ai_attempted],
          [t('סיגנלים זכאים', 'Qualified signals'), counts.signals_qualified], [t('כניסות תקפות', 'Valid entries'), counts.entries],
        ].map(([label, n]) => <div className="scanner-stat" key={String(label)}><span>{label}</span><strong>{n ?? '—'}</strong></div>)}</div>
        <p>{t('החסם הנפוץ בחלון', 'Most common recorded blocker')}: {reasons.length ? `${reasonText(reasons[0][0], he)} (${reasons[0][1]})` : t('אין חסימה מתועדת', 'No recorded blocker')}</p>
        <p className="scanner-note">{t('בדיקות חוזרות אינן הזדמנויות חדשות. השלבים מוצגים לפי הראיות שנשמרו ואינם בהכרח משפך מלא או מקונן.', 'Repeated checks are not new opportunities. Stages reflect retained evidence and are not necessarily a complete or nested funnel.')}</p>
        <p>{t('חסר מחיר בשעות מסחר רגילות', 'Missing quote during regular session')}: {data.quote_context.regular_session || 0} · {t('מחוץ לשעות מסחר רגילות', 'Outside regular session')}: {data.quote_context.outside_regular_session || 0}</p>
        <p>{t('חסימת הקצאה בסימולטור', 'Simulator allocation blocks')}: {data.execution.allocation_blocked} · {t('מילוי פקודות כניסה', 'Entry-order fill rate')}: {value(data.execution.fill_rate == null ? null : 100 * data.execution.fill_rate, '%')}</p>
        <p>{t('תשובות AI שעברו validation', 'AI responses validated')}: {counts.ai_validated ?? '—'} · {t('ניסיונות מתועדים, כולל שגיאות לפני בקשה', 'Recorded attempts, including pre-request failures')}: {counts.ai_attempt_records ?? '—'}</p>
      </>}
      {mode === 'research' && <>
        <div className="scanner-table-wrap"><table className="scanner-table"><thead><tr><th>{t('שלב החסימה', 'Blocked stage')}</th><th>{t('בדיקות', 'Observations')}</th></tr></thead><tbody>{Object.entries(data.rejection_stages).map(([stage, n]) => <tr key={stage}><td>{he ? stageNames[stage] || stage : stage}</td><td>{String(n)}</td></tr>)}</tbody></table></div>
        <details><summary>{t('סיבות מדויקות', 'Exact reasons')}</summary>{reasons.map(([reason, n]) => <p key={reason}>{reasonText(reason, he)} · {String(n)} · <bdi>{reason}</bdi></p>)}</details>
        <div className="research-filters"><label>{t('סימול', 'Ticker')} <input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} maxLength={12} /></label>
          <label>{t('כיוון', 'Direction')} <select value={side} onChange={e => setSide(e.target.value)}><option value="all">{t('הכול', 'All')}</option><option value="BUY">Long</option><option value="SELL">SELL</option><option value="SHORT">Short</option></select></label></div>
        <p className="scanner-note">{t('תצורות מדויקות במחיר ייחוס', 'Exact reference-price configurations')}: {counts.exact_reference_configurations} · {t('מוצגות עד 200 בדיקות, בעדיפות למועמדים עם החלטה או בדיקת יעד, ואז לפי זמן. הסינון חל על הרשימה המוצגת.', 'Up to 200 observations, prioritizing decisions and target checks, then newest first. Filters apply to this displayed list.')}{data.records_clipped && ` ${t('קיימות בדיקות נוספות בחלון.', 'Additional observations exist in this window.')}`}</p>
        {filtered.map((row: Row) => <Candidate key={`${row.scan_id}:${row.ticker}`} row={row} he={he} />)}
        {!filtered.length && <p>{t('אין בדיקות שמורות ברשימה לסינון הזה.', 'No retained observations match this displayed list.')}</p>}
      </>}
      {mode === 'results' && <>
        <p className="scanner-note">{t('ממוצע תוצאות סיגנלים סגורים במשקל שווה — אינו תשואת תיק. פתוחות מוצגות בנפרד לפי זמן נר הניטור. Legacy חסרה היסטוריה מלאה; Shadow אינו תיק עצמאי.', 'Equal-weight closed signal outcomes are not account return. Open positions use their timestamped monitor marks. Legacy history is incomplete; Shadow is not an independent portfolio.')}</p>
        <div className="scanner-table-wrap"><table className="scanner-table"><thead><tr>{[t('קבוצה', 'Cohort'),t('כיוון / אסטרטגיה','Side / strategy'),t('פתוחות / סגורות','Open / closed'),t('סגורות עם ראיות','Verified closed'),t('ממוצע נטו','Mean net'),t('תוחלת נטו R','Net expectancy R'),t('שיעור הצלחה','Win rate')].map(label => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{data.outcome_groups.map((g: Row) => <tr key={`${g.cohort}:${g.side}:${g.strategy}`}><td>{g.cohort}</td><td><bdi>{g.side} / {g.strategy}</bdi></td><td>{g.open} / {g.closed}</td><td>{g.verified_closed}</td><td><bdi>{value(g.mean_net_pct,'%')}</bdi></td><td><bdi>{value(g.expectancy_net_r,'R')}</bdi></td><td><bdi>{value(g.win_rate == null ? null : g.win_rate*100,'%')}</bdi></td></tr>)}</tbody></table></div>
        <p className="scanner-note">{t('כל עסקה נספרת פעם אחת; מימושים חלקיים משוקללים לפי הכמות המקורית. נטו כולל עמלות רשומות והחלקה שבמחיר הביצוע; Short אינו כולל עלויות השאלה שלא מדומות. MFE/MAE לא זמינים ללא סדרת מחירים היסטורית מתאימה.', 'Each trade counts once; partial exits are weighted by original quantity. Net includes recorded fees and execution-price slippage; Short excludes unmodelled borrow costs. MFE/MAE are unavailable without a suitable retained price series.')}</p>
        {data.outcomes.slice(0,200).map((o: Row) => <details className="research-candidate" key={o.trade_id}><summary><bdi>{o.ticker} · {o.cohort} · {o.side} · {o.status}</bdi> · {o.status==='closed' ? <bdi>{value(o.closed_net_pct,'%')} / {value(o.closed_net_r,'R')}</bdi> : t('פתוחה — אינה תוצאה סופית','Open — not a final result')}</summary>
          <p>{t('ממומש נטו כולל עמלות ששולמו','Realized net including paid fees')}: <bdi>{value(o.realized_net_pct,'%')} / {value(o.realized_net_r,'R')}</bdi></p>
          {o.status==='open' && <><p>{t('פתוח ברוטו משוקלל בכמות שנותרה','Open gross weighted by remaining quantity')}: <bdi>{value(o.open_gross_pct,'%')} / {value(o.open_gross_r,'R')}</bdi></p><p>{t('משולב לפי נר ניטור, אחרי עמלות ששולמו בלבד','Combined monitor mark after paid fees only')}: <bdi>{value(o.marked_net_pct,'%')} / {value(o.marked_net_r,'R')}</bdi> · {stamp(o.mark_at)}{o.mark_stale && ` · ${t('מחיר ישן','stale mark')}`}</p></>}
          <p>{t('מומש / נותר','Exited / remaining')}: <bdi>{value(o.exited_pct,'%')} / {value(o.remaining_pct,'%')}</bdi> · {t('עמלות יחסיות','Fees')}: <bdi>{value(o.fee_pct,'%')}</bdi> · {t('משך עסקה סגורה','Closed holding time')}: <bdi>{value(o.holding_hours,'h')}</bdi></p>
          {o.exits.map((f: Row, index: number) => <p key={index}><bdi>{f.type} · {value(f.position_pct,'%')} · {value(f.price)}</bdi> · {stamp(f.at)}</p>)}
          {o.evidence_status!=='VERIFIED_FILLS' && <p className="scanner-warning">{t('לא זמין לחישוב מאומת: היסטוריית כניסה/עמלות/יציאות חסרה.','Verified result unavailable: incomplete entry/fee/exit history.')}</p>}
        </details>)}
        {data.outcomes.length>200 && <p>{t('מוצגות 200 עסקאות אחרונות; הסיכום כולל את כל המדגם שנקרא.','Showing latest 200 trades; summary uses the full bounded sample.')}</p>}
      </>}
    </>}
  </section>
}
