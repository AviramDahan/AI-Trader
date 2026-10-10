import type { ReactNode } from 'react'
import { activeTargetIndexes } from './signalPresentation'
import { finite, LABELS, REASONS, recordTime, STATIONS, timestamp, type ActivityItem, type Row, type Station } from './systemActivityModel'
import './stockEvidence.css'

type Levels = { plan?: Row; entry: unknown; stop: unknown; activeTarget: unknown; rr: unknown }
type Pair = [string, string]
const actionNames: Record<string, Pair> = { BUY:['קנייה','Buy'], SELL:['מכירה','Sell'], SHORT:['שורט','Short'], HOLD:['המתנה','Hold'] }
const signalNames: Record<string, Pair> = {
  PENDING_ENTRY:['ממתין לביצוע כניסה','Waiting for entry'], PENDING_CLOSE:['ממתין לביצוע יציאה','Waiting for exit'],
  ENTERED:['נשמרה כניסה לפוזיציה','Position entry retained'], CLOSED:['הסתיים','Finished'],
  RISK_BLOCKED:['ביצוע הדמה נחסם בבקרת ההקצאה','Paper execution blocked by allocation controls'],
  DUPLICATE_BLOCKED:['כניסה נוספת נחסמה למניעת כפילות','Additional entry blocked to prevent duplication'],
  ENTRY_POLICY_REJECTED:['מחיר הביצוע לא עמד בבקרות הכניסה','Execution price failed entry checks'],
  RECOVERY_UNCERTAIN:['הביצוע חסום עד בירור אי־ודאות','Execution blocked pending uncertainty review'],
  EXPIRED:['פג תוקף פקודת הכניסה','Entry order expired'], CANCELLED:['בוטל','Cancelled'], REJECTED:['נדחה','Rejected'],
  HOLD:['המתנה','Hold'], BEARISH_ONLY:['איתות שלילי בלבד — ללא יציאה שבוצעה','Bearish indication only — no executed exit'],
  ACTIVE:['סיגנל פעיל — אינו הוכחת כניסה','Active signal — not proof of entry'], COMPLETED:['הסתיים','Finished'],
}
const orderNames: Record<string, Pair> = {
  pending:['ממתינה לביצוע','Pending execution'], filled:['הפקודה סומנה כמבוצעת','Order marked filled'],
  expired:['פג תוקף','Expired'], cancelled:['בוטלה','Cancelled'], rejected:['נדחתה','Rejected'],
  recovery_uncertain:['חסומה עד בירור אי־ודאות','Blocked pending uncertainty review'],
}
const reviewNames: Record<string, Pair> = {
  validated:['הפלט נבדק מבחינת המבנה — לא אישור כניסה','Response structure validated — not entry approval'],
  rejected:['הסקירה נדחתה','Review rejected'], pending:['ממתין לסקירה','Awaiting review'],
  reviewing:['הסקירה בעיבוד','Review in progress'], error:['שגיאה בסקירה','Review error'],
}
const phaseNames: Record<string, Pair> = { pre_ai:['לפני סקירת AI','Before AI review'], post_ai:['אחרי סקירת AI','After AI review'], fill:['בבדיקת הביצוע','At execution check'] }
const outcomeNames: Record<string, Pair> = { PASS:['הבדיקה עברה','Check passed'], REJECT:['הבדיקה לא עברה','Check rejected'], WAIT:['ממתין','Waiting'], WAITING:['ממתין','Waiting'], UNKNOWN:['לא ניתן לקבוע','Undetermined'] }
const exitNames: Record<string, Pair> = { tp:['מימוש ביעד','Target exit'], tp1:['מימוש ביעד הראשון','First target exit'], tp2:['מימוש ביעד השני','Second target exit'], tp3:['מימוש ביעד השלישי','Third target exit'], stop:['יציאה בסטופ','Stop exit'], sl:['יציאה בסטופ','Stop exit'], close_long:['יציאה לפי סיגנל','Signal exit'], signal:['יציאה לפי סיגנל','Signal exit'] }
const extraReasons: Record<string, Pair> = {
  pre_insufficient_confirmed_price_zones:['אין מספיק אזורי מחיר מאושרים לתוכנית','Not enough confirmed price zones'],
  pre_price_structure_fails_risk_reward:['מבנה היעדים אינו עומד בדרישות הסיכון־סיכוי','Target structure fails risk/reward requirements'],
  pre_duplicate_cooldown:['המתנה לאחר סיגנל קודם','Waiting after a previous signal'],
  target_buffer_reaches_entry:['מרווח ההתנגדות משאיר את היעד בכניסה או מתחתיה','Resistance buffer leaves the target at or below entry'],
  target_rounds_to_or_below_entry:['היעד המעוגל אינו מעל הכניסה','Rounded target is not above entry'],
  non_positive_stop:['מחיר הסטופ אינו חיובי','Stop price is not positive'],
  stop_not_below_entry:['הסטופ אינו מתחת לכניסה','Stop is not below entry'],
  rounded_target_not_before_resistance:['היעד המעוגל אינו לפני ההתנגדות','Rounded target is not before resistance'],
}
export const evidenceNumber = (value: unknown, suffix = '') => finite(value) == null ? '—' : `${finite(value)!.toFixed(2)}${suffix}`
export function evidenceTime(value: unknown, he: boolean) {
  return timestamp(value) ? new Intl.DateTimeFormat(he?'he-IL':'en-GB', { timeZone:'Asia/Jerusalem', day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false }).format(new Date(String(value))) : he?'לא נשמר':'Not retained'
}
const text = (pair: Pair, he: boolean) => pair[he?0:1]
const named = (map: Record<string,Pair>, code: unknown, he: boolean) => map[String(code)] ? text(map[String(code)],he) : code ? (he?'פרט נוסף — ראו מידע טכני':'Additional detail — see technical data') : (he?'לא נשמר':'Not retained')
export function evidenceReason(code: unknown, he: boolean): string {
  if (!code) return he?'אין סיבה נוספת שנשמרה':'No further reason retained'
  const key=String(code), pair=REASONS[key] || extraReasons[key] || REASONS[`pre_${key}`] || extraReasons[`pre_${key}`]
  return pair ? text(pair,he) : he?'סיבה נוספת שלא תורגמה — ראו מידע טכני':'Additional untranslated reason — see technical data'
}
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(v=>v && typeof v==='object') : []

/** Presentation only: missing evidence is never promoted into a passed gate. */
export function StockEvidence({item:i,levels,he,records,onClose,stale=false}: {item:ActivityItem;levels:Levels;he:boolean;records:Row[];onClose:()=>void;stale?:boolean}) {
  const t=(a:string,b:string)=>he?a:b
  const r=i.record,s=i.signal,trade=i.trade,o=i.outcome
  const checks=rows(r?.target_checks),reviews=rows(r?.reviews),orders=rows(r?.orders),ai=r?.ai_decision,sec=r?.sec_decision
  const {plan,entry,stop,activeTarget,rr}=levels
  const linkedSignals=rows(r?.signals)
  const validUntil=s?.valid_until ?? linkedSignals.find(v=>String(v.id)===String(s?.id))?.valid_until
  const policy=plan?.policy_version ?? trade?.policy_version ?? s?.policy_version ?? o?.policy_version
  const otherScans=records.filter(v=>v.ticker===i.ticker && v.scan_id!==r?.scan_id).sort((a,b)=>timestamp(recordTime(b))-timestamp(recordTime(a))).slice(0,5)
  const why=s?.reason_he || s?.reason
  const hasEvidence=!!sec || i.station==='evidence' && !!i.reason
  const available: Record<Station,boolean>={technical:!!r?.technical_recorded,targets:checks.length>0,evidence:hasEvidence,ai:!!ai||reviews.length>0,signal:!!s,order:orders.length>0,position:!!trade,exit:!!o}
  const missing=STATIONS.filter(stage=>!available[stage])
  const status=trade ? trade.status==='open'?t('פוזיציית דמה פתוחה','Open paper position'):t('פוזיציית הדמה הסתיימה','Paper position finished') : s ? named(signalNames,s.status,he) : i.state==='blocked'?t('המועמדת לא התקדמה','Candidate did not advance'):i.state==='waiting'?t('ממתין לבדיקה או למסחר','Waiting for review or market session'):t('מועמדת שנשמרה — המשך לא ידוע','Candidate retained — next step unknown')
  const explanation=trade?.legacy_position_id ? t('פוזיציה מיובאת: היסטוריית ההחלטה והביצוע עשויה להיות חלקית.','Imported position: decision and execution history may be incomplete.') : trade ? t('נמצאה רשומת פוזיציה. בדיקות מוקדמות שחסרות במדגם אינן מוצגות כאילו עברו.','A position record is present. Missing earlier checks are not presented as passed.') : s?.status==='RISK_BLOCKED' ? t('הסיגנל נשמר, אך לא הופעלה פוזיציה חדשה. חסימת הקצאה אינה פסילת איכות הסיגנל.','The signal was retained, but no new position activated. Allocation blocks are not signal-quality rejections.') : i.state==='uncertain' ? t('אין כניסה מאומתת בתצוגה הזאת. נדרש בירור של הקשר בין הפקודה לפוזיציה.','This view does not verify an entry. The order/position link needs review.') : s ? t('סיגנל או פקודה ממתינה אינם פוזיציה שבוצעה.','A signal or pending order is not an executed position.') : t('מוצגת הבדיקה שנשמרה, לא עסקה שבוצעה.','This is a retained review, not an executed trade.')
  const field=(name:string,value:ReactNode)=> <div key={name}><dt>{name}</dt><dd>{value}</dd></div>
  const num=(value:unknown,suffix='')=><bdi>{evidenceNumber(value,suffix)}</bdi>
  const at=(value:unknown)=><bdi>{evidenceTime(value,he)}</bdi>
  const section=(stage:Station,summary:string,content:ReactNode)=><details className="evidence-stage" data-evidence-stage={stage} key={stage}><summary><span className="evidence-step" aria-hidden="true">{STATIONS.indexOf(stage)+1}</span><span><strong>{text(LABELS[stage],he)}</strong><small>{summary}</small></span><span className="evidence-disclosure" aria-hidden="true">+</span></summary><div className="evidence-stage-body">{content}</div></details>
  return <section className="system-journey stock-evidence" dir={he?'rtl':'ltr'} aria-label={t('מסלול המניה','Stock journey')}>
    <header><div><span className="system-eyebrow">{t('הסבר וראיות','EXPLANATION & EVIDENCE')}</span><h3><bdi>{i.ticker}</bdi></h3><p><bdi>{i.company || t('שם החברה לא נשמר','Company name not retained')}</bdi></p></div><button type="button" onClick={onClose}>{t('סגירה','Close')}</button></header>
    <div className={`evidence-status state-${i.state}`}><strong>{status}</strong>{i.reason && <p className="evidence-main-reason">{evidenceReason(i.reason,he)}</p>}<p>{explanation}</p><small>{t('עדכון מתועד','Retained update')}: {at(i.at)} · {t('שעון ישראל','Israel time')}</small></div>
    {stale && <p className="evidence-warning">{t('העדכון מתעכב או אינו טרי. מוצג מידע שנשמר, לא פעילות חדשה.','Refresh delayed or stale. Retained information, not new activity.')}</p>}
    <section className="evidence-block"><h4>{t('כניסה, הגנה ויעד','Entry, protection & target')}</h4><dl className="evidence-grid">
      {field(t(trade?'כניסה שנשמרה':'כניסה / מחיר ייחוס',trade?'Retained entry':'Entry / reference'),num(entry))}
      {field(t('סטופ נוכחי / שנבדק','Current / checked stop'),num(stop))}
      {field(t('יעד פעיל','Active target'),num(activeTarget))}{field(t('יחס סיכוי־סיכון שנשמר','Retained reward/risk'),num(rr,'R'))}
    </dl><p className="evidence-note">{t('RR ברוטו: היחס שנשמר בתוכנית, לפני עלויות. אין כאן חישוב מחדש לפי מחיר חי.','Gross RR: the saved plan ratio before costs, not recalculated using a live quote.')}</p>
      {activeTarget==null && activeTargetIndexes(trade||s||{}).length>0 && <dl className="evidence-grid">{activeTargetIndexes(trade||s||{}).map(n=>field(t(`יעד פעיל ${n}`,`Active target ${n}`),num((trade||s||{})[`tp${n}`])))}</dl>}
    </section>
    {why && <details className="evidence-other evidence-thesis"><summary>{t('למה הסיגנל נבחר?','Why was the signal selected?')}</summary><p dir="auto">{String(why).slice(0,2400)}</p><p className="evidence-note">{t('הסבר שנשמר בזמן ההחלטה, לא המלצה חדשה.','Explanation retained at decision time, not a new recommendation.')}</p></details>}
    {o && <section className="evidence-block"><h4>{t('תוצאה עד עכשיו','Outcome so far')}</h4><dl className="evidence-grid">
      {field(t('ממומש נטו','Realized net'),<>{num(o.realized_net_pct,'%')}<small>{num(o.realized_net_r,'R')}</small></>)}
      {field(t('חלק פתוח ברוטו','Open portion gross'),<>{num(o.open_gross_pct,'%')}<small>{num(o.open_gross_r,'R')}</small></>)}
      {field(t('יתרה מהפוזיציה','Position remaining'),num(o.remaining_pct,'%'))}
      {field(t('זמן הערכת החלק הפתוח','Open valuation time'),at(o.mark_at))}
    </dl><p className="evidence-note">{t('משוקלל לפי חלקי הפוזיציה; לא תשואת תיק. ברוטו אינו נטו. מקף אומר שאין נתון, לא אפס רווח.','Weighted by position portions, not portfolio return. Gross is not net. A dash means unavailable, not zero return.')}</p>
      {o.mark_stale && <p className="evidence-warning">{t('הערכת החלק הפתוח מבוססת על נר ישן; אינה מחיר חי.','Open valuation uses an old bar, not a live quote.')}</p>}
      {o.cohort==='Legacy' && <p className="evidence-warning">{t('Legacy: חסרה היסטוריה מלאה לאימות התוצאה.','Legacy: complete history unavailable for verified results.')}</p>}
    </section>}
    <section className="evidence-block"><h4>{t('הבדיקות והפעולות שנשמרו','Retained checks & actions')}</h4><p className="evidence-note">{t('פתחו שלב לפירוט. מוצגים רק שלבים עם תיעוד; עצם קיום רשומה אינו אישור לכל הבקרות.','Expand a stage for detail. Only documented stages are shown; a record is not approval of all gates.')}</p>
      <div className="evidence-stages">
        {available.technical && section('technical',t('מועמדת תועדה בסריקה','Candidate retained in scan'),<><p>{t('תיעוד מועמדת, לא אישור שכל הבקרות עברו.','Candidate retained, not proof all controls passed.')}</p><dl className="evidence-grid">{field(t('כיוון טכני','Technical direction'),named(actionNames,r?.direction,he))}{field(t('זמן הסריקה','Scan time'),at(r?.at))}</dl></>)}
        {available.targets && section('targets',named(outcomeNames,checks.at(-1)?.outcome,he),checks.map((c,n)=><article className="evidence-check" key={n}><strong>{named(phaseNames,c.phase,he)} · {named(outcomeNames,c.outcome,he)}</strong><p>{t('זמן הבדיקה','Check time')}: {at(c.decided_at||c.observed_at)}</p>{c.rejection_reason && <p className="evidence-warning">{evidenceReason(c.rejection_reason,he)}</p>}{(Array.isArray(c.rejection_detail)?c.rejection_detail:[]).map((code:string,k:number)=><p key={k}>{evidenceReason(code,he)}</p>)}<dl className="evidence-grid">{field(t('מחיר ייחוס בבדיקה','Checked reference price'),num(c.quote?.price))}{field(t('זמן המחיר','Quote time'),at(c.quote?.as_of))}{field(t('RR שנבדק לאחר עיגול','Checked RR after rounding'),num(c.accepted_levels?.rr?.[0]??c.geometry?.rr_rounded,'R'))}{field(t('התנגדות קרובה','Nearest resistance'),num(c.geometry?.nearest_resistance?.low))}</dl>{c.quote?.eligible_for_entry===false && <p className="evidence-warning">{t('מחיר למחקר בלבד — אינו מאשר כניסה','Research-only quote — does not authorize entry')}{c.quote?.fresh===false && t('. המחיר האחרון אינו טרי.','. Last-known price is not fresh.')}</p>}{c.evidence_gap && <p className="evidence-warning">{t('חסרות ראיות מבנה — אין להסיק שהבדיקה הושלמה.','Structure evidence is incomplete; do not infer a completed check.')}</p>}</article>))}
        {available.evidence && section('evidence',sec?t('נשמר ניתוח דיווחים','Filing analysis retained'):t('נשמרה חסימה בשלב הראיות','Evidence-stage block retained'),<>{i.station==='evidence'&&i.reason&&<p className="evidence-warning">{evidenceReason(i.reason,he)}</p>}{sec&&<><dl className="evidence-grid">{field(t('מצב שימוש בדיווחים','Filing mode'),sec.mode==='paper'?t('משתתף בבחירה','Used in selection'):sec.mode==='shadow'?t('מחקר בלבד — אינו משנה בחירה','Research only — does not change selection'):sec.mode==='off'?t('כבוי','Off'):t('לא ידוע','Unknown'))}{field(t('שינוי דירוג','Rank adjustment'),num(sec.sec_adjustment))}{field(t('דירוג בסיס','Baseline rank'),num(sec.baseline_rank_score))}{field(t('דירוג משופר','Enhanced rank'),num(sec.enhanced_rank_score))}{field(t('זמן החלטת הדיווחים','Filing decision time'),at(sec.decided_at))}</dl>{sec.rejection_reason&&<p>{evidenceReason(sec.rejection_reason,he)}</p>}</>}<p className="evidence-note">{t('רשומת SEC אינה לבדה הוכחה שעבר סף הראיות. פירוט מעבר סף החדשות אינו זמין כאן.','A SEC record alone does not prove the evidence gate passed. News-gate detail is unavailable here.')}</p></>)}
        {available.ai && section('ai',ai?named(actionNames,ai.action,he):t('נשמרו ניסיונות סקירה','Review attempts retained'),<>{ai&&<dl className="evidence-grid">{field(t('החלטת המודל','Model decision'),named(actionNames,ai.action,he))}{field(t('ציון מודל לא מכויל','Uncalibrated model score'),num(ai.confidence))}{field(t('רלוונטיות שנשמרה','Retained relevance'),num(ai.news_relevance))}</dl>}{ai&&<p className="evidence-note">{t('הציון אינו הסתברות לרווח ואינו אישור כניסה.','The score is not a profit probability or entry approval.')}</p>}{(Array.isArray(ai?.filter_failures)?ai.filter_failures:[]).map((code:string,n:number)=><p className="evidence-warning" key={n}>{evidenceReason(code,he)}</p>)}{reviews.map((v,n)=><article className="evidence-check" key={n}><strong>{named(reviewNames,v.result,he)}</strong><p>{t('ניסיונות מתועדים','Recorded attempts')}: <bdi>{finite(v.attempts)??'—'}</bdi> · {at(v.at)}{v.rejection&&<><br/>{evidenceReason(v.rejection,he)}</>}</p></article>)}</>)}
        {available.signal && section('signal',named(signalNames,s?.status,he),<><dl className="evidence-grid">{field(t('פעולת הסיגנל','Signal action'),named(actionNames,s?.action,he))}{field(t('מצב ביצוע הדמה','Paper execution status'),named(signalNames,s?.status,he))}{field(t('נוצר בתאריך','Created at'),at(s?.created_at))}{field(t('תוקף פקודת הכניסה','Entry order valid until'),at(validUntil))}{field(t('מדיניות יעד','Target policy'),policy==='single_target_v2'?t('יעד יחיד — גרסה 2','Single target — version 2'):policy?t('תוכנית קודמת שנשמרה','Earlier retained plan'):t('גרסה לא נשמרה','Version not retained'))}</dl><p className="evidence-note">{t('תוקף הכניסה אינו תוקף הפוזיציה. פוזיציה קיימת ממשיכה לפי הסטופ והיעד שלה. מצב ההקצאה אינו מדד איכות הסיגנל.','Entry validity is not position expiry. Existing positions follow their stop and target. Allocation status is not signal quality.')}</p></>)}
        {available.order && section('order',orders.length===1?named(orderNames,orders[0].status,he):t(`${orders.length} פקודות נשמרו בסריקה`,`${orders.length} orders retained in scan`),<>{orders.map((v,n)=><article className="evidence-check" key={n}><strong>{v.purpose==='entry'?t('פקודת כניסה','Entry order'):v.purpose==='close_long'?t('פקודת יציאה','Exit order'):t('פקודה נוספת','Other order')}</strong><p>{named(orderNames,v.status,he)}</p></article>)}<p className="evidence-note">{linkedSignals.length>1?t('הפקודות שייכות לסריקה המקושרת; לא אומת כאן שכל פקודה שייכת לאותו סיגנל.','Orders belong to the linked scan; this view does not verify every order belongs to this signal.'):t('סטטוס פקודה אינו לבדו הוכחת עסקה שבוצעה.','Order status alone is not proof of an executed trade.')}</p></>)}
        {available.position && section('position',trade?.status==='open'?t('פתוחה','Open'):trade?.status==='closed'?t('נסגרה','Closed'):t('מצב נוסף — ראו פירוט','Additional status — see detail'),<><dl className="evidence-grid">{field(t('פתיחת הפוזיציה','Position opened'),at(trade?.opened_at))}{field(t('יתרה מהפוזיציה','Position remaining'),num(o?.remaining_pct,'%'))}{field(t('מקור הרשומה','Record origin'),trade?.legacy_position_id?t('מיובאת','Imported'):t('רשומת מנוע הדמה','Paper-engine record'))}{field(t('נר מוניטור אחרון','Last monitor bar'),at(trade?.last_bar_at))}</dl><p className="evidence-note">{t('מקור הרשומה אינו הוכחה לשרשרת מסחר חדשה מלאה בענן.','Record origin does not prove a complete new cloud trading chain.')}</p></>)}
        {available.exit && section('exit',rows(o?.exits).length?t(`${rows(o?.exits).length} מימושים מתועדים`,`${rows(o?.exits).length} retained exits`):t('אין מימוש יציאה מתועד','No retained exit fill'),<>{rows(o?.exits).map((v,n)=><article className="evidence-check" key={n}><strong>{named(exitNames,v.type,he)}</strong><p>{num(v.position_pct,'%')} {t('מהפוזיציה','of position')} · {at(v.at)}</p></article>)}<p className="evidence-note">{t('ממומש נטו עשוי לכלול עמלת כניסה גם לפני מימוש יציאה.','Realized net may include an entry fee before any exit fill.')}</p></>)}
      </div>
      {!!missing.length&&<details className="evidence-missing"><summary>{t(`מידע שאינו זמין במדגם (${missing.length})`,`Information unavailable in sample (${missing.length})`)}</summary><p>{t('מידע חסר אינו כישלון ואינו הוכחה שהשלב עבר. אין להשלים אותו מסריקה אחרת של אותה מניה.','Missing information is neither failure nor proof of a passed stage. Do not fill it from another scan of the same stock.')}</p><ul>{missing.map(stage=><li key={stage}>{text(LABELS[stage],he)}</li>)}</ul></details>}
      {s&&!why&&<p className="evidence-note">{t('הסבר הבחירה המקורי אינו זמין במדגם הזה.','The original selection explanation is unavailable in this sample.')}</p>}
    </section>
    {!!otherScans.length&&<details className="evidence-other"><summary>{t('סריקות אחרות של אותה מניה — שרשראות נפרדות','Other scans of this stock — separate chains')}</summary><p className="evidence-note">{t('לא חלק מההחלטה או מהפוזיציה שמוצגות למעלה.','Not part of the decision or position shown above.')}</p>{otherScans.map((v,n)=><article className="evidence-check" key={n}><p>{at(recordTime(v))}</p><p>{v.rejection?evidenceReason(v.rejection,he):t('אין תוצאה סופית מתועדת','No retained final result')}</p></article>)}</details>}
    <details className="evidence-technical"><summary>{t('מידע טכני ומזהי הרשומות','Technical data & record IDs')}</summary><p className="evidence-note">{t('מיועד לבדיקה ותמיכה, לא אישור מסחר.','For investigation and support, not trading approval.')}</p><dl className="evidence-grid">{field(t('סיגנל','Signal'),<bdi>{s?.id??'—'}</bdi>)}{field(t('פוזיציה','Position'),<bdi>{trade?.id??'—'}</bdi>)}{field(t('גרסת מדיניות','Policy version'),<bdi>{policy||'—'}</bdi>)}{field(t('סריקה','Scan'),<bdi>{r?.scan_id||'—'}</bdi>)}</dl><ul>{[i.reason,s?.status,s?.action,trade?.status,o?.cohort,sec?.mode,sec?.rejection_reason,...checks.flatMap(c=>[c.phase,c.outcome,c.rejection_reason,c.evidence_gap,...(Array.isArray(c.rejection_detail)?c.rejection_detail:[])]),...reviews.flatMap(v=>[v.result,v.rejection]),...orders.flatMap(v=>[`#${v.id}`,v.purpose,v.status]),ai?.action,...(Array.isArray(ai?.filter_failures)?ai.filter_failures:[])].filter(Boolean).map((code,n)=><li key={n}><code dir="ltr">{String(code)}</code></li>)}</ul></details>
    <p className="evidence-note evidence-footer">{t('צפייה בלבד. אין כאן סריקה או החלטה חדשה. Shadow אינו תיק עצמאי ואינו נכלל בתחנות הביצוע הראשיות.','Read-only. No new scan or decision. Shadow is not independent capital and is excluded from main execution stations.')}</p>
  </section>
}
