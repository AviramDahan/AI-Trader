import { useRef, useState, type CSSProperties } from 'react'
import { opsTime } from './adminSystemModel'
import { TEAM_STATES, safeTeamLink, teamMembers, type TeamReport } from './adminAgentOfficeModel'
import './adminAgentOffice.css'

function DeskIllustration({ code }: { code: string }) {
  return <svg viewBox="0 0 148 83" className="agent-desk-art" aria-hidden="true" focusable="false">
    <path className="desk-floor" d="M14 61 74 30 135 61 75 79Z" /><path className="desk-surface" d="m22 45 52-26 50 26-51 25Z" />
    <path className="desk-edge" d="M22 45v5l51 25 51-25v-5L73 70Z" /><path className="desk-leg" d="M31 54v13M114 54v13" />
    <rect className="desk-monitor" x="56" y="14" width="40" height="26" rx="4" /><path className="desk-screen-line" d="M64 24h13m-13 6h24m-13 10v7m-7 0h15" />
    <path className="desk-chair" d="M45 54q15-11 30 0v10H45Z" /><path className="desk-person" d="M49 52q0-15 12-15t12 15v6H49Z" /><circle className="desk-person" cx="61" cy="31" r="8" />
    <text x="108" y="45" textAnchor="middle" className="desk-code">{code}</text>
  </svg>
}
export function AdminAgentOffice({ report, now, fresh }: { report?: TeamReport | null; now: number; fresh: boolean }) {
  const [selected,setSelected] = useState<string>('coordinator')
  const focus = useRef<HTMLDivElement>(null)
  const map = useRef<HTMLDivElement>(null)
  const members = teamMembers(report,now,fresh), active = members.find(m => m.id === selected) ?? members[0]
  const running = members.filter(m => m.state === 'running').length, verified = members.some(m => m.state !== 'unknown')
  const link = fresh && verified ? safeTeamLink(report?.report_url) : null, published = report?.source === 'published_audit'
  const select = (id: string) => { setSelected(id); requestAnimationFrame(() => { focus.current?.scrollIntoView({behavior:'auto',block:'nearest'}); focus.current?.focus({preventScroll:true}) }) }
  return <section className="agent-office" aria-label="משרד צוות Agents">
    <header className="agent-office-heading"><div><span className="agent-office-eyebrow">THE TEAM</span><h2>משרד הצוות</h2><p>לכל עמדה אחריות ברורה. לחצו כדי לראות מה הסוכן בודק.</p></div><span className="agent-office-count"><bdi>8</bdi> תפקידים</span></header>
    <div className="agent-office-report" role="status"><span className="agent-report-icon" aria-hidden="true">◷</span><div>
      <strong>{!verified ? 'טרם התקבל דיווח צוות מאומת' : !fresh ? 'מציג דיווח שמור, לא פעילות חיה' : published ? 'הסבב האחרון הסתיים' : running ? `${running} סוכנים דווחו כפעילים` : 'דיווח הצוות האחרון'}</strong>
      <p>{published ? 'צוות הביקורת אינו עובד ברציפות. שירותי המסחר בענן ממשיכים בנפרד.' : 'הסטטוס מגיע מדיווח הרכז. הוא אינו מוכיח זמינות רציפה או תקינות מסחר.'}</p>
      <span>זמן הדיווח: <bdi>{opsTime(report?.reported_at)}</bdi> · ישראל</span>
    </div></div>
    <div className="agent-office-map" ref={map} aria-label="עמדות הסוכנים"><div className="agent-office-lane" aria-hidden="true"><span>ריכוז ובקרה</span></div>
      {members.map((member,index) => <button type="button" key={member.id} className={`agent-desk agent-${member.state} ${index === 0 || index === members.length-1 ? 'agent-desk-lead' : ''} ${selected === member.id ? 'agent-desk-selected' : ''}`} style={{'--agent-accent':member.color} as CSSProperties} aria-pressed={selected === member.id} aria-controls="agent-office-detail" onClick={() => select(member.id)}>
        <div className="agent-desk-visual"><DeskIllustration code={member.initials} /><span className="agent-desk-number" aria-hidden="true"><bdi>{String(index+1).padStart(2,'0')}</bdi></span></div>
        <div className="agent-desk-copy"><h3>{member.title}</h3><p>{member.specialty}</p><span className="agent-desk-status"><i aria-hidden="true" />{TEAM_STATES[member.state]}</span>{member.state === 'blocked' && <small className="agent-desk-blocker">{member.blocker}</small>}</div>
      </button>)}
    </div>
    <div id="agent-office-detail" ref={focus} tabIndex={-1} role="region" aria-label={`פירוט עמדה: ${active.title}`} className={`agent-office-detail agent-${active.state}`}>
      <div className="agent-detail-title"><span className="agent-detail-symbol" aria-hidden="true">{active.initials}</span><div><span>העמדה שנבחרה</span><h3>{active.title}</h3></div><span className="agent-detail-state">{TEAM_STATES[active.state]}</span></div>
      <p>{active.purpose}</p><dl><dt>המשימה בדיווח</dt><dd>{active.task ?? 'אין משימה מאומתת בדיווח'}</dd><dt>עדכון העמדה</dt><dd><bdi>{opsTime(active.observedAt)}</bdi> · ישראל</dd></dl>
      {active.blocker && <p className="agent-detail-caveat">סיבת החסם בדיווח: {active.blocker}{active.state === 'stale' ? ' · המצב הנוכחי לא אומת' : ''}</p>}
      {active.state === 'completed' && <p className="agent-detail-caveat">הסוכן סיים את סבב הבדיקה המדווח. זה לא אומר שאין ממצאים פתוחים או שהושלם אימות מסחר חי.</p>}
      {active.state === 'stale' && <p className="agent-detail-caveat">אין אישור עדכני לפעילות הסוכן. לא מציגים אותו כעובד עכשיו.</p>}
      {link && <a href={link} target="_blank" rel="noopener noreferrer">פתיחת דוח הסבב <span aria-hidden="true">↗</span></a>}
      <button type="button" className="agent-detail-back" onClick={() => { const desk=map.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]'); desk?.scrollIntoView({behavior:'auto',block:'center'}); desk?.focus({preventScroll:true}) }}>חזרה לעמדות הצוות</button>
    </div><p className="agent-office-note">העמדות מציגות חלוקת עבודה ודיווח אחרון, לא תנועת סוכנים בזמן אמת. אין כאן כפתורי הפעלה, פריסה או מסחר.</p>
  </section>
}
