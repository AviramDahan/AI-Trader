/** Read-only projection of retained evidence. Never synthesize a passed stage or fill. */
export type Row = Record<string, any>
export const STATIONS = ['technical', 'targets', 'evidence', 'ai', 'signal', 'order', 'position', 'exit'] as const
export type Station = typeof STATIONS[number]
export type ActivityItem = {
  id: string; ticker: string; company: string; station: Station
  state: 'recorded' | 'blocked' | 'waiting' | 'uncertain' | 'open' | 'closed'
  at: string | null; reason: string | null; kind: 'candidate' | 'signal' | 'position'
  record?: Row; signal?: Row; trade?: Row; outcome?: Row
}
/** Display count only; retained evidence rows remain individually accessible. */
export const stockCount = (items: ActivityItem[]) => new Set(items.map(i => i.ticker).filter(Boolean)).size
/** Only retained, open main trades are active positions; signals/orders are not fills. */
export const activePositionItems = (items: ActivityItem[]) => items.filter(item =>
  item.kind === 'position' && item.state === 'open' && item.trade?.status === 'open' && !item.trade.is_shadow)
// Presentation symbols, never approval/profit indicators; closed includes expiry.
export const STATE_SYMBOLS: Record<ActivityItem['state'],string> = {recorded:'·',blocked:'×',waiting:'…',uncertain:'?',open:'●',closed:'■'}

export const finite = (n: unknown): number | null => n != null && n !== '' && typeof n !== 'boolean' && Number.isFinite(Number(n)) ? Number(n) : null
export const timestamp = (s: unknown): number => typeof s === 'string' && Number.isFinite(Date.parse(s)) ? Date.parse(s) : 0
export function newestTime(values: unknown[]): string | null {
  const stamps = values.filter((v): v is string => timestamp(v) > 0)
  return stamps.sort((a, b) => timestamp(b) - timestamp(a))[0] || null
}
export function recordTime(r: Row): string | null {
  return newestTime([r.at, r.sec_decision?.decided_at, ...(r.target_checks || []).map((c: Row) => c.observed_at || c.decided_at), ...(r.reviews || []).map((v: Row) => v.at)])
}
export function rejectionStation(r: Row): Station {
  if (r.rejection_stage === 'news' || /news_provider|insufficient_current_news/.test(r.rejection || '')) return 'evidence'
  if (r.rejection_stage === 'ai_filter' || /^ai_|sec_material_conflict|news_sentiment_conflict/.test(r.rejection || '')) return 'ai'
  if (r.rejection_stage === 'targets' || /zone|stop|target|resistance|risk_reward|rounded/.test(r.rejection || '')) return 'targets'
  return 'technical' // quote/session/unknown: not evidence that downstream checks passed
}
export function candidateItem(r: Row): ActivityItem {
  const attempts = finite(r.ai_attempts) || 0
  const wait = r.rejection_stage === 'session_wait' || /waiting_regular_session|cooldown/.test(r.rejection || '')
  return { id: `scan:${r.scan_id}:${r.ticker}`, ticker: r.ticker, company: r.company || '', kind: 'candidate',
    station: r.rejection ? rejectionStation(r) : r.ai_decision || attempts > 0 ? 'ai' : (r.target_checks || []).length ? 'targets' : 'technical',
    state: wait ? 'waiting' : r.rejection ? 'blocked' : 'recorded', at: recordTime(r), reason: r.rejection || null, record: r }
}

export function buildActivity(research: Row | null, dashboard: Row | null): ActivityItem[] {
  const records: Row[] = research?.records || []
  const since = timestamp(research?.window_since)
  const trades: Row[] = (dashboard?.trades || []).filter((t: Row) => !t.is_shadow &&
    (t.status === 'open' || !since || !timestamp(t.closed_at) || timestamp(t.closed_at) >= since))
  const signalMap = new Map<string, Row>()
  for (const r of records) for (const s of r.signals || []) signalMap.set(String(s.id), { ...s, ticker: r.ticker, company: r.company, created_at: r.at })
  for (const s of dashboard?.signals || []) {
    const terminal = ['EXPIRED','CANCELLED','REJECTED','CLOSED','COMPLETED'].includes(s.status)
    if (!s.legacy_unverified && !(terminal && since && timestamp(s.updated_at || s.created_at) && timestamp(s.updated_at || s.created_at) < since)) signalMap.set(String(s.id), s)
  }
  const signals = [...signalMap.values()]
  const bySignal = new Map<string, Row>(signals.map(s => [String(s.id), s]))
  const tradeSignals = new Set(trades.map(t => String(t.signal_id)))
  const linked = new Set<string>()
  const items: ActivityItem[] = trades.map(t => {
    const s = bySignal.get(String(t.signal_id))
    const record = records.find(r => r.signals?.some((v: Row) => String(v.id) === String(t.signal_id)))
    if (record) linked.add(`${record.scan_id}:${record.ticker}`)
    const o = (research?.outcomes || []).find((v: Row) => String(v.trade_id) === String(t.id))
    return { id: `trade:${t.id}`, ticker: t.ticker, company: s?.company || record?.company || '',
      station: t.status === 'open' ? 'position' : 'exit', state: t.status === 'open' ? 'open' : 'closed',
      at: newestTime([t.closed_at, o?.mark_at, t.last_bar_at, t.opened_at]), reason: null, kind: 'position', trade: t, signal: s, record, outcome: o }
  })
  for (const s of signals) {
    if (tradeSignals.has(String(s.id))) continue
    const r = records.find(v => v.signals?.some((v: Row) => String(v.id) === String(s.id)))
    if (r) linked.add(`${r.scan_id}:${r.ticker}`)
    const orders: Row[] = (r?.orders || []).filter((o: Row) => o.purpose === 'entry')
    const uncertain = orders.some(o => o.status === 'recovery_uncertain') || s.status === 'RECOVERY_UNCERTAIN'
    const pending = orders.some(o => o.status === 'pending')
    const expired = ['EXPIRED', 'CANCELLED', 'REJECTED', 'CLOSED', 'COMPLETED'].includes(s.status)
    const blocked = ['RISK_BLOCKED', 'DUPLICATE_BLOCKED', 'ENTRY_POLICY_REJECTED'].includes(s.status)
    // Actual_entry alone without a linked trade is not a proven current position.
    const unlinkedFill = s.actual_entry != null || orders.some(o => o.status === 'filled')
    items.push({ id: `signal:${s.id}`, ticker: s.ticker, company: s.company || r?.company || '',
      station: uncertain || pending || orders.length ? 'order' : 'signal',
      state: uncertain || unlinkedFill ? 'uncertain' : blocked ? 'blocked' : expired ? 'closed' : 'waiting',
      at: newestTime([s.updated_at, s.created_at, recordTime(r || {})]),
      reason: uncertain ? 'recovery_uncertain' : unlinkedFill ? 'unlinked_fill' : s.status === 'RISK_BLOCKED' ? 'allocation_blocked' : blocked || expired ? s.status : null,
      kind: 'signal', signal: s, record: r })
  }
  // One latest retained scan per ticker; repeated scans remain separately accessible in detail.
  const latest = new Map<string, Row>()
  for (const r of records) {
    if (r.signals?.length || linked.has(`${r.scan_id}:${r.ticker}`)) continue
    const old = latest.get(r.ticker)
    if (!old || timestamp(recordTime(r)) > timestamp(recordTime(old))) latest.set(r.ticker, r)
  }
  for (const r of latest.values()) items.push(candidateItem(r))
  return items.sort((a, b) => timestamp(b.at) - timestamp(a.at) || a.id.localeCompare(b.id))
}

export function activityRevision(item: ActivityItem): string {
  // Ignore wall-clock response timestamps: polling the same evidence must not animate.
  return JSON.stringify([item.id, item.station, item.state, item.at, item.reason,
    item.record?.target_checks, item.record?.reviews, item.record?.ai_decision,
    item.record?.orders, item.signal?.status, item.trade?.remaining_quantity,
    item.trade?.current_stop, item.outcome?.exit_types])
}

export type ActivityUpdate = { key: string; item: ActivityItem }
/** New retained evidence since the viewer baseline, never a reconstruction of unseen work. */
export function detectActivityUpdates(previous: ActivityItem[] | null, current: ActivityItem[], baselineAt: number, now: number): ActivityUpdate[] {
  if (!previous || !baselineAt || now < baselineAt) return []
  const known = new Map(previous.map(i => [i.id, i]))
  return current.filter(i => {
    const at = timestamp(i.at), old = known.get(i.id)
    if (!at || at > now || now - at > 150000) return false
    if (!old) return at >= baselineAt // historical rows newly exposed by a capped report aren't live events
    return at > timestamp(old.at) && activityRevision(i) !== activityRevision(old)
  }).sort((a,b) => timestamp(a.at) - timestamp(b.at) || a.id.localeCompare(b.id))
    .map(item => ({ key: `${item.id}:${item.at}`, item }))
}

export const LABELS: Record<Station, [string, string]> = {
  technical: ['סריקה וטכני', 'Scan & technical'], targets: ['יעדים ו־RR', 'Targets & RR'],
  evidence: ['חדשות ו־SEC', 'News & SEC'], ai: ['סקירת AI', 'AI review'],
  signal: ['סיגנל שנשמר', 'Retained signal'], order: ['פקודת דמה', 'Paper order'],
  position: ['פוזיציה פעילה', 'Open position'], exit: ['יציאה ותוצאה', 'Exit & outcome'],
}
export const STATE_LABELS: Record<ActivityItem['state'], [string, string]> = {
  recorded: ['שלב מתועד — המשך לא ידוע', 'Recorded — next stage unknown'], blocked: ['נחסם', 'Blocked'],
  waiting: ['ממתין', 'Waiting'], uncertain: ['דורש בירור', 'Needs review'], open: ['פעילה', 'Open'], closed: ['הסתיים', 'Finished'],
}
export const REASONS: Record<string, [string, string]> = {
  pre_no_fresh_quote: ['אין מחיר ייחוס טרי', 'No fresh reference quote'],
  pre_waiting_regular_session: ['ממתין למסחר הרגיל', 'Waiting for regular session'],
  post_waiting_regular_session: ['המסחר הסתיים בזמן הבדיקה', 'Session ended during review'],
  pre_nearest_resistance_below_2r: ['התנגדות קרובה לפני 2R', 'Nearest resistance below 2R'],
  pre_entry_inside_unresolved_price_zone: ['כניסה בתוך אזור לא פתור', 'Entry inside unresolved zone'],
  pre_no_forward_zone: ['אין אזור התנגדות קדמי', 'No forward resistance zone'],
  pre_no_structural_stop_anchor: ['אין עוגן סטופ מבני', 'No structural stop anchor'],
  pre_structural_stop_too_distant: ['הסטופ המבני רחוק מדי', 'Structural stop too distant'],
  pre_invalid_rounded_levels: ['רמות אינן תקינות לאחר עיגול', 'Invalid rounded levels'],
  insufficient_current_news: ['אין ראיות חדשות עדכניות מספיקות', 'Insufficient current evidence'],
  news_provider_unavailable_fail_closed: ['מקור החדשות אינו זמין', 'News provider unavailable'],
  ai_hold: ['החלטת AI: המתנה', 'AI decision: HOLD'],
  ai_or_confidence_filter: ['החלטת AI או ציון לא עברו', 'AI decision or score rejected'],
  ai_confidence_below_threshold: ['ציון המודל מתחת לסף', 'Model score below threshold'],
  ai_news_relevance_below_threshold: ['רלוונטיות מתחת לסף', 'Relevance below threshold'],
  news_sentiment_conflict: ['סתירה בכיוון החדשות', 'News direction conflict'],
  sec_material_conflict_hold: ['סתירה מהותית בראיות SEC', 'Material SEC conflict'],
  recovery_uncertain: ['אי־ודאות בהתאוששות — אין כניסה מאומתת', 'Recovery uncertain — entry not verified'],
  allocation_blocked: ['סיגנל כשיר; הקצאת הדמה חסומה', 'Qualified signal; paper allocation blocked'],
  unlinked_fill: ['דווח ביצוע ללא פוזיציה מקושרת — נדרש בירור', 'Reported fill without linked position — needs review'],
  DUPLICATE_BLOCKED: ['כניסה נוספת נחסמה — כפילות', 'Additional entry blocked — duplicate'],
  ENTRY_POLICY_REJECTED: ['מחיר הביצוע לא עבר את בקרות הכניסה', 'Execution price failed entry gates'],
  EXPIRED: ['פג תוקף ללא כניסה מאומתת', 'Expired without a verified entry'],
  CLOSED: ['סיגנל הסתיים — פרטי פוזיציה אינם במדגם', 'Signal closed — position detail absent from sample'],
}
