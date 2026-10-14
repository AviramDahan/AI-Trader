export type OpsState = 'healthy' | 'idle' | 'failed' | 'degraded' | 'stale' | 'unknown' | 'disabled'
export type OpsNode = {
  id: string; state: OpsState; reason: string; observed_at: string | null
  age_seconds?: number | null; last_success_at?: string | null; lease_holders?: number | null
  metrics: Record<string, number | boolean | string | null>
  reason_codes?: string[]
  providers?: { id: string; status: string; last_success_at: string | null; last_attempt_at?: string | null;
    next_check_at?: string | null; error_code?: string | null; http_status?: number | null }[]
  bars?: { ticker: string; bar_started_at: string | null; fresh_regular_session: boolean | null }[]
}
export type OpsSnapshot = {
  version: number; observed_at: string; build_sha: string | null; read_only: boolean
  overall: 'failed' | 'attention' | 'observed_operational'
  market: { is_open: boolean; reason: string }; nodes: OpsNode[]
}
export const OPS_GROUPS = [
  { title: 'מקורות ומידע', ids: ['news_feed', 'sec_intelligence'] },
  { title: 'בחירת מועמדות', ids: ['quotes', 'scan'] },
  { title: 'סקירה וניתוח', ids: ['ai_local', 'ai_cloud', 'news_ai'] },
  { title: 'מחזור חיי הדמה', ids: ['paper', 'monitor'] },
  { title: 'מסירת עדכונים', ids: ['telegram'] },
]
export const OPS_ROLE_LEASE_NODES = new Set(['news_feed', 'sec_intelligence', 'scan', 'quotes', 'news_ai', 'monitor', 'telegram'])
/** Checkpoint completion is discovery coverage, not all documents parsed. */
export function secDiscoveryCoverage(node: OpsNode): { completed: number; total: number; remaining: number } | null {
  const total = node.metrics.issuers, completed = node.metrics.completed
  if (typeof total !== 'number' || typeof completed !== 'number' || !Number.isSafeInteger(total) ||
      !Number.isSafeInteger(completed) || total <= 0 || total > 10**9 || completed < 0 || completed > total) return null
  return { completed, total, remaining: total - completed }
}
export function marketDescription(data: OpsSnapshot | null, fresh: boolean): string {
  if (!data || typeof data.market?.is_open !== 'boolean') return 'מצב השוק לא אומת'
  if (!fresh) return `מצב השוק לא אומת כעת; בתמונה השמורה: ${data.market.is_open ? 'מסחר פתוח' : 'מחוץ למסחר הרגיל'}`
  return data.market.is_open ? 'המסחר הרגיל פתוח' : 'מחוץ למסחר הרגיל; הניטור לפי חלונו'
}
export const OPS_NODES: Record<string, { title: string; subtitle: string; purpose: string }> = {
  news_feed: { title: 'מקורות חדשות', subtitle: 'איסוף ותור עיבוד', purpose: 'מצב האיסוף והכיסוי לפי הספקים; אין כאן הורדת חדשות יזומה.' },
  sec_intelligence: { title: 'דיווחי SEC', subtitle: 'דוחות ובעלי עניין', purpose: 'תקינות הרכיב והשלמת גילוי הדיווחים מוצגות בנפרד. מוני ההשלמה מתייחסים לגילוי אצל המנפיקים, לא להוכחה שכל מסמך עובד או שכל המידע נתמך.' },
  quotes: { title: 'נתוני מחירים', subtitle: 'ציטוטים שמורים', purpose: 'מצב רענון המחירים הקיים. מחוץ למסחר הרגיל אין כאן הוכחה למחיר מסחר חי.' },
  scan: { title: 'סורק מניות', subtitle: 'סינון ודירוג', purpose: 'מצב המחזור האחרון והבא. אין סיגנלים הוא מצב תקין, לא תקלה כשלעצמו.' },
  ai_local: { title: 'Ollama במחשב', subtitle: 'שער AI פרטי', purpose: 'תצפית החיבור והמוכנות מהענן. מוכנות מודל אינה הוכחה לסקירת מניה מוצלחת; עומס או טעינה אינם ניתוק.' },
  ai_cloud: { title: 'OpenRouter', subtitle: 'גיבוי לפי דרישה', purpose: 'התקציב והקרדיטים לפי ההתאמה האחרונה. לא נשלחת קריאת בדיקה; זמינות תקציב אינה הוכחת חיבור או תשובת AI.' },
  news_ai: { title: 'ניתוח חדשות', subtitle: 'איכות וראיות', purpose: 'מצב מסלול עיבוד החדשות. אין עבודה חדשה אינו מחייב קריאת AI לצורך הצגת פעילות.' },
  paper: { title: 'סיגנלים ופקודות', subtitle: 'מסחר מדומה בלבד', purpose: 'פקודה ממתינה אינה פוזיציה. רק כניסה חוקית שהושלמה מפעילה פוזיציה; אי־ודאות דורשת הכרעה נפרדת.' },
  monitor: { title: 'ניטור פוזיציות', subtitle: 'כניסה · יעד · סטופ', purpose: 'בעלות עובד, בדיקת הניטור ונרות שהושלמו מוצגים בנפרד. נר שמור או שוק סגור אינם הוכחה לביצוע עסקה חדשה.' },
  telegram: { title: 'Telegram', subtitle: 'תורים ומסירה', purpose: 'מצב העובד וגיל התור. תור ריק אינו הוכחה שההודעה נקראה בפועל בטלגרם.' },
  backup: { title: 'גיבוי מוצפן', subtitle: 'Recovery State', purpose: 'ההצלחה השמורה במסלול הגיבוי המוצפן הקיים. אין יצירת גיבוי או שחזור מכאן, ואין אימות מחדש של התוכן בכל רענון.' },
  database: { title: 'PostgreSQL', subtitle: 'תמונת מצב עקבית', purpose: 'הצלחת שאילתות בקריאה בלבד באותה תמונת מצב. אינה התאמת חשבונאות מלאה או בדיקת שחזור.' },
  api: { title: 'API', subtitle: 'גישה מוגנת', purpose: 'השרת השיב לבקשת ניטור מורשית. זה אינו אישור שכל שאר הרכיבים תקינים.' },
}
export const OPS_REASONS: Record<string, string> = {
  no_observation: 'עדיין אין תצפית שמורה', invalid_or_missing_timestamp: 'זמן התצפית חסר או אינו תקין',
  observation_stale: 'לא התקבלה בדיקה חדשה בזמן הצפוי', reported_error: 'הרכיב דיווח על כשל',
  reported_degraded: 'הרכיב דיווח על פעולה חלקית', idle: 'אין כרגע עבודה לביצוע', waiting: 'ממתין למחזור הבא',
  market_closed: 'מחוץ לחלון המסחר הפעיל', no_new: 'הבדיקה הושלמה ללא מידע חדש',
  not_modified: 'הבדיקה הושלמה ללא שינוי במקור', no_signals: 'הסריקה הושלמה ללא סיגנל שעבר את הבקרות',
  retry_backoff: 'ממתין לניסיון חוזר לפי מדיניות ההתאוששות', component_disabled: 'הרכיב כבוי או אינו פעיל בהגדרה',
  scan_schedule_overdue: 'זמן המחזור הבא חלף ללא השלמה עדכנית', scan_in_progress: 'מחזור סריקה בתהליך לפי הסטטוס השמור; טרם הושלם',
  recent_completed_check: 'בדיקת הרכיב האחרונה הושלמה', lease_missing: 'אין עובד בעל lease פעיל לתפקיד',
  duplicate_role_lease: 'נצפתה יותר מבעלות אחת לתפקיד', canonical_alarm: 'בדיקת הצינור דיווחה על חריגה',
  partial_provider_coverage: 'הצינור פועל, אך חלק מהמקורות דורשים טיפול',
  completed_bars_not_fresh: 'יש מחיר/נר חסר או ישן בזמן המסחר הרגיל',
  recovery_review_required: 'יש פקודה חסומה באי־ודאות; אין לנחש ביצוע',
  retained_paper_state: 'מצב הדמה שנשמר, לא ביצוע יזום', local_route_disabled: 'השימוש במסלול המקומי כבוי',
  model_ready_not_inference_proof: 'השער מחובר והמודל מוכן לפי בדיקת הבריאות',
  private_relay_unavailable: 'החיבור הפרטי או זהות המודל אינם תקינים',
  gpu_busy_or_loading: 'השער נגיש, אך המודל עסוק או נטען', recovery_verification_pending: 'המוכנות חזרה; אימות ההתאוששות עדיין נמשך',
  invalid_observation: 'תשובת הבריאות אינה מוכרת',
  paid_fallback_budget_available_not_connection_proof: 'התקציב זמין; הגיבוי מופעל רק לפי דרישה',
  paid_fallback_budget_or_credits_blocked: 'התקציב או הקרדיטים חוסמים קריאה בתשלום',
  budget_observation_unavailable: 'אין נתוני תקציב עדכניים ומאומתים', delivery_backlog: 'ממתינות הודעות יותר מחמש דקות',
  read_only_snapshot_succeeded: 'שאילתות תמונת המצב הצליחו', authenticated_api_response: 'בקשת הניטור המורשית נענתה',
}
export const OPS_STATES: Record<OpsState, string> = { healthy: 'תקין לפי התצפית', idle: 'פעיל / בהמתנה', failed: 'דורש טיפול', degraded: 'פעולה חלקית', stale: 'תצפית ישנה', unknown: 'לא אומת', disabled: 'כבוי בהגדרה' }
export const OPS_ERROR_CODES: Record<string, string> = {
  stale_or_missing_bars:'נרות חסרים או ישנים', TimeoutError:'תם זמן ההמתנה', ReadTimeout:'המקור לא השלים תשובה בזמן',
  ConnectTimeout:'לא נוצר חיבור בזמן', ConnectionError:'שגיאת חיבור', HTTPError:'המקור דחה את הבקשה',
  ValueError:'הנתון או המבנה אינם תקינים', RuntimeError:'כשל תפעולי מדווח', OperationalError:'כשל גישה למסד',
  invalid_json:'תשובת AI אינה JSON תקין', budget_exhausted:'תקציב AI חסום', news_quality_rejected:'דחיית תוכן בבקרת איכות, לא כשל שירות',
}
export function providerExplanation(provider: NonNullable<OpsNode['providers']>[number]): string | null {
  if (provider.http_status === 403) return 'המקור דחה את הגישה (403); לא אומתה התאוששות'
  if (provider.http_status === 429) return 'המקור הגביל בקשות (429); ממתינים לפי מדיניות ההתאוששות'
  return ({ transport_failure:'הבקשה לא הושלמה בגלל כשל בחיבור', transport_TimeoutError:'המקור לא השלים תשובה בזמן',
    source_metadata_invalid:'מטא־דאטה של המקור לא עבר אימות', press_feed_activation_required:'חסרה הגדרת תחילת איסוף מאושרת',
    license_required:'חסרה הרשאת שימוש מאושרת', http_error:'המקור דחה את בקשת האיסוף' } as Record<string,string>)[provider.error_code ?? ''] ?? null
}
export const OPS_METRICS: Record<string, string> = {
  queue: 'אירועים בתור', oldest_queue_seconds: 'גיל האירוע הוותיק (שניות)', provider_issues: 'מקורות דורשים טיפול',
  issuers: 'מנפיקים במעקב איסוף', completed: 'מנפיקים ששלב הגילוי הושלם אצלם', errors: 'שגיאות במעקב האיסוף',
  next_scan_at: 'סריקה הבאה', last_completed_at: 'הסריקה שהושלמה', universe_count: 'מניות ביקום',
  technical_candidates_count: 'מועמדות טכניות במחזור', ai_selected_count: 'נבחרו לסקירה במחזור', signals_published: 'סיגנלים שנשמרו במחזור',
  sampled_cursors: 'נרות מניות במדגם', regular_session_open: 'המסחר הרגיל פתוח', open_positions: 'פוזיציות פעילות',
  pending_orders: 'פקודות ממתינות לכניסה', holds: 'פקודות באי־ודאות', budget_available: 'תקציב גיבוי זמין',
  public_delivery_queued: 'הודעות קהילה בתור', admin_delivery_queued: 'הודעות Admin בתור',
  public_delivery_oldest_seconds: 'גיל הודעת קהילה (שניות)', admin_delivery_oldest_seconds: 'גיל הודעת Admin (שניות)', schema: 'גרסת Schema',
}
export function isAdminSystemEntry(search: string, hash: string): boolean {
  const query = new URLSearchParams(search), fragment = new URLSearchParams(hash.slice(1))
  return query.get('ops') === '1' || query.get('tgWebAppStartParam') === 'operations' || fragment.get('tgWebAppStartParam') === 'operations'
}
export function telegramAdminData(win: Window = window): string {
  const raw = (win as Window & { Telegram?: { WebApp?: { initData?: unknown } } }).Telegram?.WebApp?.initData
  return typeof raw === 'string' && raw.length <= 8192 ? raw : ''
}
export function snapshotFresh(data: OpsSnapshot | null, now: number): boolean {
  if (!data || data.version !== 1 || data.read_only !== true) return false
  const at = Date.parse(data.observed_at)
  return Number.isFinite(at) && now - at >= -5000 && now - at <= 45000
}
export function opsTime(value: string | null | undefined): string {
  if (!value || !Number.isFinite(Date.parse(value))) return 'לא זמין'
  return new Intl.DateTimeFormat('he-IL', { timeZone: 'Asia/Jerusalem', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value))
}
