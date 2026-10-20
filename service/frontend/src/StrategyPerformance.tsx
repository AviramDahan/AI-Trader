import { useEffect, useState } from 'react'
import { API_ORIGIN } from './appShared'
import { createReadPoller } from './readPoller'

type Row = Record<string, any>
const names: Record<string, [string, string]> = {
  BASELINE: ['מסלול הבסיס', 'Baseline'],
  VCP_BASE_CONTRACTION: ['התכווצות בסיס ופריצה', 'VCP base contraction'],
  STOCKBEE_MOMENTUM_BURST: ['התפרצות מומנטום', 'Momentum burst'],
  PEAD: ['המשך תנועה אחרי דוחות', 'Post-earnings drift'],
  TREND_PULLBACK_RECLAIM: ['תיקון וחזרה למגמה', 'Trend pullback reclaim'],
  RELATIVE_STRENGTH_LEADER: ['מובילת חוזק יחסי', 'Relative-strength leader'],
  UNATTRIBUTED: ['רשומות ללא מקור מאומת', 'Unattributed records'],
}
const title = (key: string, he: boolean) => names[key]?.[he ? 0 : 1] || key
const number = (value: unknown, suffix = '') => value != null && Number.isFinite(Number(value))
  ? `${Number(value).toFixed(2)}${suffix}` : null

export function StrategyPerformance({ he, hours: selectedHours, setHours: selectHours }: { he: boolean; hours?:number; setHours?:(hours:number)=>void }) {
  const [ownHours, setOwnHours] = useState(48)
  const hours=selectedHours??ownHours, setHours=selectHours??setOwnHours
  const [data, setData] = useState<Row | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    setData(null)
    setError(false)
    const poller=createReadPoller<Row>({
      url:`${API_ORIGIN}/api/scanner/strategy-performance?hours=${hours}`,intervalMs:60000,
      onData:result=>{
        if (result?.version !== 1 || !Array.isArray(result.strategy_rows) ||
            !Array.isArray(result.exact_set_groups) || !result.overall || !result.coverage) throw new Error('invalid-response')
        setData(result);setError(false)
      },onError:()=>setError(true),
    })
    poller.start()
    return ()=>poller.stop()
  }, [hours])
  return <StrategyPerformanceView he={he} data={data} error={error} hours={hours} setHours={setHours} />
}

function Counts({ row, he }: { row: Row, he: boolean }) {
  const counts = row.counts || {}
  const labels = [
    ['signals', 'סיגנלים בחלון', 'Signals in window'],
    ['pending_entry_orders', 'פקודות כניסה ממתינות', 'Pending entry orders'],
    ['actual_entries', 'כניסות בפועל בחלון', 'Actual entries in window'],
    ['open_trades', 'פוזיציות פתוחות', 'Open positions'],
    ['fully_closed_trades', 'נסגרו בחלון', 'Closed in window'],
    ['partial_exit_trades', 'פתוחות עם מימוש חלקי', 'Open with partial exit'],
  ]
  return <dl className="strategy-performance-counts">{labels.map(([key, hebrew, english]) =>
    <div key={key}><dt>{he ? hebrew : english}</dt><dd><bdi>{counts[key] ?? (he ? 'לא ידוע' : 'Unknown')}</bdi></dd></div>)}</dl>
}

function Metrics({ row, he }: { row: Row, he: boolean }) {
  const m = row.metrics || {}
  const missing = he ? 'טרם ניתן לחשב' : 'Not yet available'
  const metrics = [
    [he ? 'שיעור הצלחה נטו' : 'Closed net win rate', number(m.closed_win_rate == null ? null : m.closed_win_rate*100, '%')],
    [he ? 'ממוצע תשואה נטו לעסקה סגורה' : 'Mean closed trade net return', number(m.mean_closed_net_pct, '%')],
    [he ? 'תוחלת נטו לעסקה סגורה' : 'Closed net expectancy', number(m.expectancy_net_r, 'R')],
    ['Profit Factor', number(m.profit_factor)],
  ]
  return <div className="strategy-performance-metrics">
    <p>{he ? 'סגורות עם ראיות במדגם שנקרא' : 'Verified closed trades in the retained sample'}: <bdi>{m.verified_closed ?? (he ? 'לא ידוע' : 'Unknown')}</bdi></p>
    <dl>{metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><bdi>{value ?? missing}</bdi></dd></div>)}</dl>
    {m.profit_factor_status === 'UNDEFINED_NO_LOSSES' && <p className="strategy-performance-explanation">{he
      ? 'Profit Factor אינו מוגדר כשאין עסקאות סגורות מפסידות. אין כאן יחס אינסופי או הוכחת יתרון.'
      : 'Profit Factor is undefined without closed losing trades; this is not an infinite result or evidence of an edge.'}</p>}
    {!m.verified_closed && <p className="strategy-performance-explanation">{he
      ? 'עדיין אין עסקאות סגורות עם ראיות מספיקות. פקודה ממתינה אינה עסקה, ופוזיציה פתוחה אינה הצלחה או כישלון סופיים.'
      : 'No sufficiently verified closed trades yet. A pending order is not a trade, and an open position is not a final win or loss.'}</p>}
    {String(m.status || '').startsWith('PARTIAL') && <p className="strategy-performance-warning">{he
      ? 'הראיות או ייחוס מקור הכניסה אינם מלאים; מדדי התוצאה נשארים לא ידועים.'
      : 'Execution evidence or entry attribution is incomplete; outcome metrics remain unknown.'}</p>}
    {!!row.counts?.partial_exit_trades && <p>{he ? 'ממומש נטו בפוזיציות שעדיין פתוחות, במשקל הכמות המקורית' : 'Realized net on still-open positions, weighted by original quantity'}:
      {' '}<bdi>{number(m.open_realized_mean_net_pct, '%') ?? missing} / {number(m.open_realized_mean_net_r, 'R') ?? missing}</bdi></p>}
    <p className="strategy-performance-explanation">{he
      ? 'נטו כולל את העמלות שנשמרו. ההחלקה כבר במחירי הביצוע; לא מנכים אותה שוב. R משתמש בסיכון המקורי, לא בסטופ המעודכן.'
      : 'Net includes retained fees. Slippage is already in fill prices and is not subtracted twice. R uses original risk, not the updated stop.'}</p>
  </div>
}

export function StrategyPerformanceView({ he, data, error = false, hours = 48, setHours = () => {} }: {
  he: boolean, data: Row | null, error?: boolean, hours?: number, setHours?: (hours: number) => void,
}) {
  const t = (a: string, b: string) => he ? a : b
  const stamp = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleString(he ? 'he-IL' : 'en-GB') : t('לא ידוע', 'Unknown')
  return <section className="scanner-section strategy-performance" dir={he ? 'rtl' : 'ltr'} aria-label={t('ביצועי מסלולי כניסה', 'Entry strategy performance')}>
    <header className="strategy-performance-header"><div><h2>{t('ביצועי מסלולי כניסה', 'Entry strategy performance')}</h2>
      <p>{t('מסיגנל שמור לכניסה אמיתית בסימולטור', 'From a retained signal to an actual paper entry')}</p></div>
      <label>{t('חלון התצפית', 'Observation window')} <select value={hours} onChange={event => setHours(Number(event.target.value))}>
        <option value={24}>24 {t('שעות', 'hours')}</option><option value={48}>48 {t('שעות', 'hours')}</option><option value={168}>7 {t('ימים', 'days')}</option>
      </select></label></header>
    {error && <p role="alert" className="strategy-performance-warning">{t('העדכון לא התקבל. אין להסיק שחסרות עסקאות או שהמערכת נעצרה. נתונים קודמים, אם מוצגים, אינם תצפית חדשה.', 'Refresh unavailable. This does not establish zero trades or a stopped system. Any retained display is not a new observation.')}</p>}
    {!data && !error && <p role="status">{t('קורא רשומות ביצוע שמורות בלבד…', 'Reading retained execution records only…')}</p>}
    {data && <>
      <p className="strategy-performance-time">{t('חלון סיגנלים וסגירות', 'Signal and closure window')}: <bdi>{stamp(data.window_since)}</bdi> · <bdi>{stamp(data.as_of)}</bdi></p>
      <p className="strategy-performance-explanation">{t('פתוחות ופקודות ממתינות הן המצב הנוכחי השמור, גם אם נוצרו לפני החלון. עסקה נספרת פעם אחת; מספר מימושים אינו מספר עסקאות.', 'Open positions and pending orders show current retained state, including older entries. Each trade counts once; fills are not separate trades.')}</p>
      {data.coverage?.status === 'PARTIAL' && <p className="strategy-performance-warning">{t('המדגם או ייחוס המקור אינם מלאים. “לא ידוע” אינו אפס; לא משחזרים החלטות חסרות.', 'Sample or source attribution is incomplete. Unknown is not zero; missing decisions are not reconstructed.')}</p>}
      <CoverageNotes coverage={data.coverage} he={he}/>
      <p className="strategy-performance-explanation">{t('מסלולי האיתור פועלים במקביל: מספיק זיהוי במסלול אחד כדי ליצור מועמדת. אחר כך חלות בקרות החדשות, AI, סיכון וביצוע המשותפות. מועמדת אינה סיגנל מאושר או פוזיציה.','Discovery routes run in parallel: one route can nominate a candidate. Shared news, AI, risk and execution controls still apply. A candidate is not an approved signal or a position.')}</p>
      <div className="strategy-performance-overall"><h3>{t('סך הכול, ללא כפילות בין מסלולים', 'Overall, without duplicate route attribution')}</h3><Counts row={data.overall || {}} he={he} /></div>
      <p className="strategy-performance-warning">{t('אותה מניה יכולה להתאים לכמה מסלולים. הכרטיסים הבאים חופפים ואין לחבר את המספרים או התשואות שלהם. ממוצע נטו לעסקה אינו תשואת תיק.', 'One candidate may match several routes. The cards below overlap: do not add their counts or returns. Mean trade net return is not portfolio return.')}</p>
      <div className="strategy-performance-grid">{(data.strategy_rows || []).map((row: Row) => <article className="strategy-performance-card" key={row.strategy_id}>
        <header><h3>{title(row.strategy_id, he)}</h3><span className={`strategy-performance-badge ${row.enabled === true ? 'configured' : ''}`}>
          {row.strategy_id === 'UNATTRIBUTED' ? t('מקור לא מאומת', 'Unverified source') : row.enabled === true ? t('גילוי מוגדר כמופעל', 'Discovery configured on') : row.enabled === false ? t('גילוי מוגדר ככבוי', 'Discovery configured off') : t('הגדרה לא ידועה', 'Configuration unknown')}</span></header>
        <Counts row={row} he={he} />
        {row.strategy_id!=='BASELINE'&&row.strategy_id!=='UNATTRIBUTED'&&<p className="strategy-performance-explanation">{t('תצפיות זיהוי שנשמרו, לא מניות ייחודיות','Retained detection observations, not unique stocks')}: {row.detector_states && Object.keys(row.detector_states).length ? Object.entries(row.detector_states).filter(([,value])=>typeof value==='number'&&Number.isInteger(value)&&value>=0).map(([state,value])=>`${({DETECTED:t('אותרה תצורה','Detected'),FORMING:t('בהתהוות','Forming'),REJECTED:t('לא התאימה לתבנית','No pattern match'),UNKNOWN:t('נתונים חסרים','Missing data')} as Record<string,string>)[state]||t('מצב נוסף','Other state')}: ${value}`).join(' · ') : t('אין תצפית שמורה במדגם','No retained observation in sample')}</p>}
        <details><summary>{t('תוצאות נטו ואיכות הראיות', 'Net outcomes and evidence quality')}</summary><Metrics row={row} he={he} /></details>
      </article>)}</div>
      <p className="strategy-performance-explanation">{t('התג מתאר הגדרת גילוי בלבד, לא אישור לפתוח פוזיציה. עצירת כניסות ובקרות המסחר נבדקות בנפרד.', 'Badges describe discovery configuration only, not permission to open a position. Entry pause and trading gates are separate controls.')}</p>
      <details className="strategy-performance-method"><summary>{t('קבוצות ללא חפיפה ומתודולוגיית החישוב', 'Disjoint groups and calculation method')}</summary>
        <p>{t('כל קבוצה מחזיקה את צירוף מקורות הכניסה שנשמר בפועל. מקור של סיגנל SELL שסגר עסקה לא מחליף את מקור הכניסה. מסלול כבוי אינו מוחק היסטוריה או מבטל פקודות שמורות.', 'Each group uses the original saved entry contributor set. A closing SELL does not replace entry attribution. Disabling a route does not delete history or cancel stored orders.')}</p>
        {(data.exact_set_groups || []).map((row: Row, index: number) => <article className="strategy-performance-exact" key={index}>
          <h4>{(row.strategy_ids || []).map((key: string) => title(key, he)).join(' + ')}</h4><Counts row={row} he={he} /><Metrics row={row} he={he} />
        </article>)}
        {!(data.exact_set_groups || []).length && <p>{t('אין רשומות ביצוע שמורות בקבוצה שנקראה.', 'No retained execution records in the selected cohort.')}</p>}
        <p>{t('Legacy חסרה היסטוריית פתיחה מלאה; Shadow אינו חשבון הון עצמאי. שניהם מחוץ למדדי הביצוע הראשיים.', 'Legacy lacks complete opening history; Shadow has no independent capital account. Both are excluded from primary performance metrics.')}
          {' '}<bdi>Legacy: {data.excluded_cohorts?.Legacy?.trades ?? t('לא ידוע', 'Unknown')} · Shadow: {data.excluded_cohorts?.Shadow?.trades ?? t('לא ידוע', 'Unknown')}</bdi></p>
        <p>{t('מדדי drawdown ותשואת תיק לפי מסלול אינם זמינים ללא היסטוריית הון מתאימה. יותר סיגנלים אינם הוכחת שיפור ברווחיות.', 'Route drawdown and portfolio returns are unavailable without appropriate equity history. More signals do not prove better profitability.')}</p>
      </details>
    </>}
  </section>
}

function CoverageNotes({coverage,he}:{coverage:Row;he:boolean}) {
  const t=(a:string,b:string)=>he?a:b
  const gaps:Record<string,[string,string]>={
    signal_attribution_unavailable:['חסר ייחוס מסלול בסיגנלים','Signal route attribution missing'],
    entry_order_attribution_unavailable_or_mismatch:['ייחוס פקודות כניסה חסר או אינו תואם','Entry order attribution missing or mismatched'],
    trade_entry_attribution_unavailable_or_mismatch:['ייחוס הכניסה לעסקאות חסר או אינו תואם; אין לשייך אותן בדיעבד למסלול חדש','Trade entry attribution missing or mismatched; never assign old trades to a new route retrospectively'],
    trade_fill_history_unverified:['היסטוריית ביצועים ועמלות אינה מאומתת במלואה','Fill and fee history is not fully verified'],
    discovery_observation_unavailable:['תיעוד הזיהוי חלקי','Detection evidence incomplete'],
  }
  const issues=Object.entries(coverage?.evidence_gaps||{}).filter(([,n])=>typeof n==='number'&&n>0)
  return <details className="strategy-performance-coverage"><summary>{t('מה מכוסה ומה חסר במדדים?','What is covered and missing?')}</summary>
    <p>{t('חוסר בייחוס של רשומה אחת עלול להפוך את ספירות המסלולים ללא ידועות גם כשסך הכול מאומת. אפס עסקאות סגורות אינו שיעור הצלחה של 0%.','One unattributed record can make route counts unknown even when overall totals are known. Zero closed trades is not a 0% win rate.')}</p>
    {coverage?.clipped?.length>0&&<p>{t('מדגם הרשומות מוגבל; אין להסיק שכיסוי החלון מלא.','The record sample is capped; full window coverage is not established.')}</p>}
    {!!issues.length&&<ul>{issues.map(([code,n])=><li key={code}>{gaps[code]?.[he?0:1]||t('פער תיעוד נוסף','Additional evidence gap')}: <bdi>{String(n)}</bdi></li>)}</ul>}
    <p>{t('חברות היסטורית ב־shortlist ותחרות על מכסת AI אינן משוחזרות; אין להציג שיעורי מעבר שלא נשמרו.','Historical shortlist membership and AI quota competition are not reconstructed; unstored conversion rates are not available.')}</p>
  </details>
}
