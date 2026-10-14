export type TeamState = 'queued' | 'running' | 'completed' | 'blocked' | 'unknown' | 'stale'
export type TeamReport = { version: number; source: string; reason: string; run_id: string | null; reported_at: string | null; report_url: string | null; agents: { id: string; state: TeamState; task: string; observed_at: string | null; blocker_code?: string | null }[] }
export const AGENT_ROLES = [
  { id: 'coordinator', title: 'רכז הצוות', specialty: 'תמונה מלאה והחלטות', purpose: 'מאחד ממצאים, מוודא בדיקות ומפריד בין תיקון מוצע לבין אישור פריסה.', initials: 'C', color: '#e6bb7b' },
  { id: 'trading', title: 'מנוע המסחר', specialty: 'כניסה · יעד · סטופ', purpose: 'בודק פקודות דמה, חשבונאות ושריון. אינו יוצר עסקאות כדי להוכיח תקינות.', initials: 'T', color: '#89c6e5' },
  { id: 'data', title: 'נתונים וראיות', specialty: 'חדשות · דיווחי SEC', purpose: 'בודק מקורות, זהות חברה, טריות, כיסוי ומניעת שימוש במידע מהעתיד.', initials: 'D', color: '#9ccda5' },
  { id: 'infrastructure_security', title: 'תפעול ואבטחה', specialty: 'שירותים · גיבוי · גישה', purpose: 'בודק זמינות, בלעדיות עובדים, משאבים, גיבוי ויעד חזרה בטוח.', initials: 'O', color: '#acb7e8' },
  { id: 'ai', title: 'איכות AI', specialty: 'תשובות · ניתוב · עלות', purpose: 'בודק מבנה תשובות, שמירת עובדות ועלויות, בלי לשנות מודל או לעקוף HOLD תקף.', initials: 'A', color: '#b4a5e5' },
  { id: 'ui_telegram', title: 'ממשק וטלגרם', specialty: 'מובייל · עברית · בהירות', purpose: 'בודק שימוש במובייל, RTL והסברים בכרטיסים ובהודעות. תצוגה אינה הוכחת משלוח.', initials: 'U', color: '#e5a59b' },
  { id: 'independent_qa', title: 'בקרת איכות', specialty: 'בדיקה עצמאית ורגרסיות', purpose: 'בודק מחדש את התיקונים ומחפש פגיעה במסלולים קיימים לפני שחרור.', initials: 'Q', color: '#8ad3cb' },
  { id: 'research_improvements', title: 'מחקר ושיפורים', specialty: 'המלצות לפי ראיות', purpose: 'מציע שיפורים לפי ממצאים ומבדיל בין השערה לבין שיפור שהוכח. אינו מבטיח תשואה.', initials: 'R', color: '#d4bd91' },
] as const
export const TEAM_STATES: Record<TeamState,string> = { running:'עובד לפי הדיווח', queued:'ממתין למשימה', completed:'סיים את הסבב', blocked:'דווח חסם', unknown:'לא אומת', stale:'דיווח הפעילות ישן' }
export const TEAM_TASKS: Record<string,string> = {
  coordination:'ריכוז ממצאים ובדיקת מוכנות', trading_correctness:'נכונות מנוע המסחר וההתאוששות', data_evidence:'אימות מקורות, טריות ומידע SEC', operations_security:'תקינות תפעולית, גיבוי ואבטחה',
  ai_validation:'אימות תשובות AI ושמירת חיוב', mobile_presentation:'בהירות התצוגה במובייל ובטלגרם', independent_verification:'בדיקה עצמאית של התיקונים', improvement_proposals:'הצעות שיפור מבוססות ראיות',
}
export const TEAM_BLOCKERS: Record<string,string> = {needs_approval:'ממתין לאישור מפורש',access_unavailable:'חסרה גישה נדרשת לבדיקה',required_test_failed:'בדיקה נדרשת נכשלה',missing_evidence:'חסרה ראיה להכרעה',dependency_pending:'ממתין להשלמת תלות'}
export function safeTeamLink(value: unknown): string | null { return typeof value === 'string' && /^https:\/\/github\.com\/AviramDahan\/AI-Trader\/pull\/[1-9][0-9]{0,5}$/.test(value) ? value : null }
export function teamMembers(report: TeamReport | null | undefined, now: number, authorizedFresh: boolean) {
  const reportAt = report?.reported_at ? Date.parse(report.reported_at) : NaN
  const valid = report?.version === 1 && ['published_audit','coordinator_report'].includes(report.source) && Array.isArray(report.agents) && report.agents.length <= 8 && Number.isFinite(reportAt) && now-reportAt >= -5000
  return AGENT_ROLES.map(role => {
    const matches = valid ? report!.agents.filter(a => a?.id === role.id) : []
    const row = matches.length === 1 ? matches[0] : undefined
    const at = row?.observed_at ? Date.parse(row.observed_at) : NaN
    const timeValid = Number.isFinite(at) && now-at >= -5000 && at <= reportAt
    let state: TeamState = row && Object.prototype.hasOwnProperty.call(TEAM_STATES,row.state) && timeValid ? row.state : 'unknown'
    if (state !== 'unknown' && (!authorizedFresh || (['running','queued','blocked'].includes(state) && now-at > 180000))) state = 'stale'
    return { ...role, state, observedAt:timeValid ? row!.observed_at : null, task:row && Object.prototype.hasOwnProperty.call(TEAM_TASKS,row.task) ? TEAM_TASKS[row.task] : null,
      blocker:row?.state === 'blocked' ? row.blocker_code && Object.prototype.hasOwnProperty.call(TEAM_BLOCKERS,row.blocker_code) ? TEAM_BLOCKERS[row.blocker_code] : 'הדיווח לא כלל סיבה מאומתת לחסם' : null }
  })
}
