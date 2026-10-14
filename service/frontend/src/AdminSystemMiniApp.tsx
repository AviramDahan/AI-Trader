import { useEffect, useRef, useState } from 'react'
import { API_ORIGIN } from './appShared'
import { createReadPoller } from './readPoller'
import { AdminAgentOffice } from './AdminAgentOffice'
import { OPS_GROUPS, OPS_NODES, OPS_STATES, OPS_REASONS, OPS_METRICS, OPS_ERROR_CODES, OPS_ROLE_LEASE_NODES, secDiscoveryCoverage, marketDescription, providerExplanation, opsTime, snapshotFresh, telegramAdminData, type OpsNode, type OpsSnapshot } from './adminSystemModel'
import './adminSystemMiniApp.css'

function OpsCard({ node, retained }: { node: OpsNode; retained: boolean }) {
  const identity = OPS_NODES[node.id]
  if (!identity) return null
  const state = retained ? 'stale' : node.state
  const discovery = node.id === 'sec_intelligence' ? secDiscoveryCoverage(node) : null
  return <details className={`ops-card ops-${state}`}>
    <summary><div className="ops-card-name"><span className="ops-indicator" aria-hidden="true" /><h3>{identity.title}</h3><span className="ops-expand" aria-hidden="true">＋</span></div>
      <p className="ops-subtitle">{identity.subtitle}</p>
      <span className="ops-state">{node.id === 'sec_intelligence' ? 'תקינות הרכיב: ' : ''}{OPS_STATES[state] ?? 'לא אומת'}</span>
      <p className="ops-reason">{retained ? 'מציג מידע שמור; העדכון הנוכחי לא אומת' : OPS_REASONS[node.reason] ?? 'אין הסבר מאומת לתצפית זו'}</p>
      {node.id === 'sec_intelligence' && <div className={`ops-coverage ops-${retained || !discovery ? 'unknown' : discovery.remaining ? 'degraded' : 'healthy'}`}>
        <span>{retained ? 'השלמת הגילוי לפי הנתונים השמורים' : 'השלמת גילוי דיווחים'}</span>
        <strong>{discovery ? <><bdi>{`הושלמו ${discovery.completed} מתוך ${discovery.total}`}</bdi><br />{discovery.remaining ? `נותרו ${discovery.remaining} להשלמה` : 'שלב הגילוי הושלם'}</> : 'מצב השלמת הגילוי לא אומת'}</strong>
      </div>}
      <time className="ops-time">{opsTime(node.observed_at)} · ישראל</time>
    </summary>
    <div className="ops-evidence"><p>{identity.purpose}</p>
      {node.reason_codes?.some(code => code in OPS_ERROR_CODES) && <p>סוג הכשל שדווח: {node.reason_codes.filter(code => code in OPS_ERROR_CODES).map(code => OPS_ERROR_CODES[code]).join(' · ')}</p>}
      <dl><dt>זמן התצפית</dt><dd><bdi>{opsTime(node.observed_at)}</bdi></dd>
        {node.last_success_at && <><dt>הצלחה אחרונה</dt><dd><bdi>{opsTime(node.last_success_at)}</bdi></dd></>}
        {OPS_ROLE_LEASE_NODES.has(node.id) && node.lease_holders !== undefined && <><dt>בעלות עובד לתפקיד</dt><dd>{node.lease_holders === null ? 'לא אומתה' : node.lease_holders === 1 ? 'יחידה' : node.lease_holders}</dd></>}
        {Object.entries(node.metrics).filter(([key]) => key in OPS_METRICS).map(([key, value]) => <div className="ops-metric-row" key={key}><dt>{OPS_METRICS[key]}</dt><dd><bdi>{value === null ? 'לא זמין' : typeof value === 'boolean' ? value ? 'כן' : 'לא' : key.endsWith('_at') ? opsTime(String(value)) : String(value)}</bdi></dd></div>)}
      </dl>
      {node.providers && <div className="ops-providers"><h4>מצב המקורות</h4>{node.providers.map(p => <div className="ops-provider" key={p.id}><div><bdi>{p.id}</bdi><span>{({'ok':'תקין','no_new':'אין מידע חדש','not_modified':'ללא שינוי','disabled':'כבוי','retired':'לא פעיל','error':'תקלה','requires_configuration':'נדרש טיפול / אישור גישה','backoff':'בהמתנה להתאוששות','rate_limited':'הוגבל קצב הבקשות','degraded':'כיסוי חלקי'} as Record<string,string>)[p.status] ?? 'לא אומת'}</span></div>
        {providerExplanation(p) && <p>{providerExplanation(p)}</p>}
        {p.last_attempt_at && <small>בדיקת מקור: <bdi>{opsTime(p.last_attempt_at)}</bdi> · ישראל</small>}
        {p.last_success_at && <small>הצלחה אחרונה: <bdi>{opsTime(p.last_success_at)}</bdi> · ישראל</small>}
      </div>)}</div>}
      {node.bars && <div className="ops-providers"><h4>נרות שהושלמו · מדגם עד 32 מניות</h4>{node.bars.length === 0 ? <p>אין נרות למדגם במסלול הפעיל.</p> : node.bars.map(bar => <div key={bar.ticker}><bdi>{bar.ticker}</bdi><span>{opsTime(bar.bar_started_at)}<br />{bar.fresh_regular_session === null ? 'טריות מסחר רגיל לא נבדקה: שוק סגור' : bar.fresh_regular_session ? 'נר מלא ועדכני' : 'חסר / ישן / לא גמור'}</span></div>)}</div>}
    </div>
  </details>
}

export function AdminSystemPanel({ data, error = '', now = Date.now(), onRefresh, updating = false }: {
  data: OpsSnapshot | null; error?: string; now?: number; onRefresh?: () => void; updating?: boolean
}) {
  const [view,setView] = useState<'systems' | 'team'>('systems')
  const fresh = snapshotFresh(data, now) && !error
  const nodes = new Map(data?.nodes.map(n => [n.id, n]) ?? [])
  const getNode = (id: string): OpsNode => nodes.get(id) ?? { id, state: 'unknown', reason: 'no_observation', observed_at: null, metrics: {} }
  const discovery = secDiscoveryCoverage(getNode('sec_intelligence'))
  const incompleteDiscovery = !discovery || discovery.remaining > 0
  const status = !fresh ? 'unknown' : data?.overall === 'failed' ? 'failed' : data?.overall === 'attention' || incompleteDiscovery ? 'degraded' : 'healthy'
  const summary = !data ? 'ממתין לתמונת מצב מורשית' : !fresh ? 'העדכון האחרון אינו מאומת כעת' : status === 'failed' ? 'יש רכיב שדורש טיפול' : data?.overall === 'observed_operational' && discovery && discovery.remaining > 0 ? 'המערכת פועלת; גילוי הדיווחים בהשלמה' : status === 'degraded' ? 'המערכת פועלת; יש פערים לבדיקה' : 'פעילות תקינה לפי התצפיות הזמינות'
  return <section className="ops-app" dir="rtl" aria-label="מרכז בקרת המערכת">
    <header className="ops-header"><div className="ops-eyebrow"><span className="ops-lock" aria-hidden="true">◈</span> AI TRADER <span>ADMIN ONLY</span></div>
      <h1>חדר הבקרה</h1><p>שירותי המערכת וצוות הביקורת. שתי תצוגות נפרדות, ללא פעולות מהמסך.</p>
      <div className={`ops-overview ops-${status}`} aria-live="polite"><span className="ops-indicator" aria-hidden="true" /><div><strong>{summary}</strong><small>{data ? `תמונת מצב: ${opsTime(data.observed_at)} · שעון ישראל` : 'אין נתונים עד לאימות הגישה'}</small></div></div>
      {error && <p className="ops-warning" role="alert">{error}</p>}
      <div className="ops-toolbar"><span>{marketDescription(data, Boolean(fresh))}<br /><small>רענון אוטומטי כל 15 שניות כשהמסך פתוח</small></span><button type="button" onClick={onRefresh} disabled={!onRefresh || updating}>{updating ? 'קורא מצב…' : 'רענון תצוגה'}</button></div>
    </header>
    <div className="ops-view-switch" role="tablist" aria-label="תצוגת חדר הבקרה" onKeyDown={event => {
      if (!['ArrowRight','ArrowLeft','Home','End'].includes(event.key)) return
      event.preventDefault()
      const next = event.key === 'Home' ? 'systems' : event.key === 'End' ? 'team' : view === 'systems' ? 'team' : 'systems'
      setView(next); event.currentTarget.querySelector<HTMLButtonElement>(`#ops-${next}-tab`)?.focus()
    }}>
      <button type="button" id="ops-systems-tab" role="tab" aria-selected={view === 'systems'} aria-controls="ops-systems-panel" tabIndex={view === 'systems' ? 0 : -1} onClick={() => setView('systems')}>המערכות</button>
      <button type="button" id="ops-team-tab" role="tab" aria-selected={view === 'team'} aria-controls="ops-team-panel" tabIndex={view === 'team' ? 0 : -1} onClick={() => setView('team')}>צוות Agents</button>
    </div>
    <div id="ops-team-panel" role="tabpanel" aria-labelledby="ops-team-tab" hidden={view !== 'team'}>{view === 'team' && <AdminAgentOffice report={data?.agent_team} now={now} fresh={Boolean(fresh)} />}</div>
    <div id="ops-systems-panel" role="tabpanel" aria-labelledby="ops-systems-tab" hidden={view !== 'systems'}>
    <div className="ops-flow" aria-label="זרימת המערכת"><p className="ops-map-note">הקווים מציגים קשרים בין רכיבים, לא הוכחה שעסקה עברה את כל השלבים. לחצו על רכיב לפירוט.</p>
      {OPS_GROUPS.map((group, i) => <section className="ops-stage" key={group.title}><div className="ops-stage-heading"><span>{i+1}</span><h2>{group.title}</h2></div><div className="ops-stage-cards">{group.ids.map(id => <OpsCard key={id} node={getNode(id)} retained={Boolean(data && !fresh)} />)}</div></section>)}
    </div>
    <section className="ops-infrastructure"><h2>תשתית שמחזיקה את המערכת</h2><p>מסד הנתונים והגיבוי תומכים בכל השלבים; הם אינם תחנות ביצוע עסקה.</p><div className="ops-stage-cards">{['api','database','backup'].map(id => <OpsCard key={id} node={getNode(id)} retained={Boolean(data && !fresh)} />)}</div></section>
    </div>
    <footer className="ops-footer"><details><summary>מה התצוגה מוכיחה, ומה לא?</summary><p>הנתונים נקראים מתמונת מצב עקבית בקריאה בלבד. סימון תקין מתייחס לבדיקה ולזמן שמוצגים, לא להבטחת זמינות רציפה.</p><p>אין כאן בדיקת Docker/OOM, קריאת AI יזומה, אימות קריאת הודעה בטלגרם, שחזור גיבוי או הוכחה לשרשרת מסחר טבעית מלאה. נתון חסר אינו אפס ואינו הצלחה.</p><p>התצוגה אינה משנה ספים, פקודות, פוזיציות או תקציב.</p></details><span>גרסת שרת <bdi>{data?.build_sha?.slice(0, 7) ?? 'לא אומתה'}</bdi> · תצוגה פרטית לקריאה בלבד</span></footer>
  </section>
}

export function AdminSystemMiniApp({ token }: { token: string | null }) {
  const [initData, setInitData] = useState(() => telegramAdminData())
  const [data, setData] = useState<OpsSnapshot | null>(null)
  const [error, setError] = useState('')
  const [now, setNow] = useState(Date.now())
  const [updating, setUpdating] = useState(false)
  const refresh = useRef<(() => Promise<void>) | null>(null)
  useEffect(() => {
    const ready = () => setInitData(telegramAdminData())
    window.addEventListener('ai-trader:miniapp-ready', ready)
    ready()
    return () => window.removeEventListener('ai-trader:miniapp-ready', ready)
  }, [])
  useEffect(() => {
    if (!initData && !token) {
      setError('פתחו דרך הכפתור בקבוצת הלוגים כדי לאמת גישה. הקישור לבדו אינו הרשאה.')
      return
    }
    setUpdating(true)
    const poller = createReadPoller<OpsSnapshot>({ url: `${API_ORIGIN}/api/admin/system-status`, intervalMs: 15000, timeoutMs: 12000,
      headers: () => {
        const headers: Record<string, string> = {}
        if (initData) headers['X-Telegram-Init-Data'] = initData
        else headers.Authorization = `Bearer ${token}`
        return headers
      },
      onData: value => {
        if (value.version !== 1 || value.read_only !== true || !Array.isArray(value.nodes)) { setError('השרת החזיר תמונת מצב לא מוכרת. הנתונים לא אושרו.'); return }
        setData(value); setError(''); setNow(Date.now())
      },
      onError: problem => {
        if (problem === 'HTTP 401' || problem === 'HTTP 403') setData(null)
        setError(problem === 'HTTP 401' ? 'אימות Telegram פג או חסר. סגרו ופתחו מחדש דרך קבוצת הלוגים.' : problem === 'HTTP 403' ? 'הגישה מוגבלת לחברי קבוצת הלוגים; חברותכם לא אושרה.' : problem === 'HTTP 503' ? 'לא ניתן לאמת גישה או לקבל מצב מהשרת כעת. אין כאן הוכחה לתקינות הרכיבים.' : 'העדכון מהשרת לא התקבל. אם מוצגים נתונים, הם שמורים ואינם מצב חי מאומת.')
      }, onSettled: () => setUpdating(false),
    })
    refresh.current = async () => { setUpdating(true); await poller.refresh() }
    poller.start()
    const clock = setInterval(() => setNow(Date.now()), 10000)
    return () => { refresh.current = null; poller.stop(); clearInterval(clock) }
  }, [initData, token])
  return <AdminSystemPanel data={data} error={error} now={now} updating={updating} onRefresh={initData || token ? () => void refresh.current?.() : undefined} />
}
