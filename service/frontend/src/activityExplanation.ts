/** Explanations from the exact retained chain only; never a new trading decision. */
import { finite, type ActivityItem, type Row, type Station } from './systemActivityModel'
import { reasonDefinition, reasonKey, reasonTitle, type Pair } from './activityReasons'
import { entryRejectionCode, entryPriceWait } from './signalPresentation'
import { targetFacts, targetReasonCode } from './targetDiagnostics'
const text=(pair:Pair,he:boolean)=>pair[he?0:1]
const rows=(value:unknown):Row[]=>Array.isArray(value)?value.filter(v=>v&&typeof v==='object'):[]
export const STATION_GUIDES: Record<Station, { what:Pair; next:Pair }> = {
  technical:{what:['איתור מועמדות לפי מחיר, מגמה ותקינות נתונים. תיעוד מועמדת אינו אישור כניסה.','Find candidates using price, trend and data validity. A retained candidate is not an entry approval.'],next:['בהמשך נבדקים מחיר הכניסה, הסטופ והיעד. לא כל מועמדת נשלחת לסקירת AI.','Entry, stop and target are checked next. Not every candidate receives AI review.']},
  targets:{what:['האם הכניסה, הסטופ והיעד עומדים בחוזה התוכנית וביחס הסיכוי־סיכון?','Do entry, stop and target meet the retained plan and reward/risk requirements?'],next:['מעבר הבדיקה הזאת אינו אישור לחדשות, ל-AI או לביצוע.','Passing this check does not approve evidence, AI or execution.']},
  evidence:{what:['נדרשת ראיית חדשות או SEC רלוונטית, מאומתת ועדכנית בזמן ההחלטה.','Relevant, verified and current news or SEC evidence is required at decision time.'],next:['מידע חסר או מקור לא זמין אינם חדשות שליליות. ראיה תקפה מאפשרת את המשך הבדיקה, לא כניסה אוטומטית.','Missing data or an unavailable source is not negative news. Valid evidence enables further review, not automatic entry.']},
  ai:{what:['סקירת ההחלטה והבקרות על הציון, הרלוונטיות והתאמת הכיוון.','Review the decision and gates on score, relevance and direction.'],next:['תשובה תקינה מבחינת מבנה אינה אישור כניסה. הציון אינו הסתברות לרווח.','A structurally valid response is not entry approval. The score is not a profit probability.']},
  signal:{what:['סיגנל נשמר עם כיוון, רמות ותוקף. זה עדיין לא ביצוע ולא פוזיציה פעילה.','A signal retains direction, levels and validity. It is not yet a fill or an active position.'],next:['זכאות הסיגנל נפרדת מאישור ההקצאה והביצוע בתיק הדמה.','Signal eligibility is separate from paper allocation and execution approval.']},
  order:{what:['פקודת דמה נבדקת מול מחיר הביצוע, נר שהושלם וחלון התוקף שלה.','A paper order is checked against execution price, a completed candle and its validity window.'],next:['רק ביצוע כניסה מקושר פותח פוזיציה. פקודה ממתינה, שפגה או באי־ודאות אינה כניסה שבוצעה.','Only a linked entry fill opens a position. Pending, expired and uncertain orders are not executed entries.']},
  position:{what:['פוזיציית דמה פתוחה לאחר כניסה, עם ניטור הסטופ והיעד השמורים.','An open paper position after entry, with monitoring of its retained stop and target.'],next:['מימוש חלקי משאיר רק את החלק שנותר פתוח. רשומה מיובאת עשויה להיות חסרה היסטוריית כניסה.','Partial exits leave only the remaining portion open. Imported positions may lack entry history.']},
  exit:{what:['יציאות ותוצאות לפי מילויים מקושרים, באחוזים וב-R.','Exits and outcomes from linked fills, in percent and R.'],next:['ממומש נטו נפרד מהערכת חלק פתוח ברוטו. תוצאה חסרה אינה אפס, וזו אינה תשואת תיק.','Realized net is separate from open gross valuation. Missing results are not zero; this is not portfolio return.']},
}
export function linkedItemOrders(item:ActivityItem):Row[] {
  const signalId=item.signal?.id??item.trade?.signal_id
  if(signalId==null)return []
  return rows(item.record?.orders).filter(o=>o.signal_id!=null && String(o.signal_id)===String(signalId))
}
export function matchingTargetCheck(item:ActivityItem):Row|undefined {
  if(!item.reason)return undefined
  return [...rows(item.record?.target_checks)].reverse().find(c=>c.rejection_reason &&
    (!item.reason!.startsWith('pre_')||c.phase==='pre_ai') && reasonKey(c.rejection_reason)===reasonKey(item.reason))
}
export function itemReasonCodes(item:ActivityItem):string[] {
  const codes:string[]=[]
  const add=(code:unknown)=>{if(typeof code==='string'&&code&&!codes.some(c=>reasonKey(c)===reasonKey(code)))codes.push(code)}
  // A verified exact execution blocker leads the list, not its generic status.
  if(item.signal?.status==='ENTRY_POLICY_REJECTED')add(entryRejectionCode(item.signal,linkedItemOrders(item)))
  const wait=item.state==='waiting'?entryPriceWait(item.signal,linkedItemOrders(item)):null
  if(wait){add('entry_price_wait');add(wait.reason)}
  add(item.reason)
  if(item.kind==='candidate' && item.station==='ai' && item.reason)
    for(const code of Array.isArray(item.record?.ai_decision?.filter_failures)?item.record!.ai_decision.filter_failures:[])add(code)
  const detail=matchingTargetCheck(item)?.rejection_detail
  for(const code of Array.isArray(detail)?detail:[])add(code)
  return codes
}
export function activityStatusLabel(item:ActivityItem,he:boolean):string {
  const t=(a:string,b:string)=>he?a:b
  if(item.state==='open')return t('פוזיציה פעילה','Open position')
  if(item.state==='closed')return item.kind==='position'?t('הפוזיציה נסגרה','Position closed'):itemReasonCodes(item).length?reasonTitle(itemReasonCodes(item)[0],he):t('הסיגנל הסתיים','Signal finished')
  if(item.state==='uncertain')return item.reason==='close_recovery_uncertain'?t('יציאה לא מאומתת — נדרש בירור','Exit unverified — needs review'):t('כניסה לא מאומתת — נדרש בירור','Entry unverified — needs review')
  if(item.reason){const definition=reasonDefinition(item.reason)
    if(definition.kind==='processing')return t('העיבוד לא הושלם','Processing incomplete')
    if(item.state==='blocked')return item.kind==='signal'?t('ביצוע הדמה נחסם','Paper execution blocked'):t('לא עברה את הבדיקה','Check did not pass')
    if(definition.kind==='wait')return t('ממתין — לא פסילת איכות','Waiting — not a quality rejection')
  }
  if(item.state==='waiting')return item.signal?.status==='PENDING_CLOSE'?t('ממתין לביצוע יציאה','Waiting for exit'):item.station==='order'?t('ממתין לביצוע כניסה','Waiting for entry'):t('ממתין להמשך הבדיקה','Waiting for further review')
  return t('תיעוד בלבד — המשך לא ידוע','Recorded only — next step unknown')
}
export type Explanation = {title:string; detail:string; next:string; reasons:{code:string;title:string;detail:string}[]; facts:{label:string;value:string}[]; modelReason:string|null}
export function explainActivity(item:ActivityItem,he:boolean):Explanation {
  const t=(a:string,b:string)=>he?a:b
  const codes=itemReasonCodes(item), check=matchingTargetCheck(item), ai=item.record?.ai_decision
  const displayCodes=[...new Set(codes.map(code=>check&&reasonKey(code)===reasonKey(check.rejection_reason)?targetReasonCode(check):code))]
  const reasons=displayCodes.map(code=>({code,title:reasonTitle(code,he),detail:text(reasonDefinition(code).detail,he)}))
  let title=reasons[0]?.title||activityStatusLabel(item,he)
  let detail=reasons[0]?.detail||t('נשמרה רשומה בשלב הזה, אך לא נשמרה תוצאה סופית. אין להסיק שהשלב הבא עבר.','This stage has a retained record but no final result. Passing the next stage is not inferred.')
  let next=t('התוצאה שייכת לבדיקה הזאת. החלטה אחרת דורשת בדיקה חדשה עם נתונים תקפים.','This result belongs to this check. A different decision requires a new check with valid data.')
  if(item.kind==='position'){
    title=activityStatusLabel(item,he)
    detail=item.trade?.status==='open'?t('נמצאה פוזיציית דמה פתוחה. מנגנון הניטור ממשיך לנהל את הסטופ והיעד שלה.','An open paper position is retained. Monitoring manages its stop and target.'):t('נמצאה פוזיציה סגורה. סיבת היציאה נקבעת רק ממילויי יציאה מקושרים.','A closed position is retained. Only linked exit fills establish the exit cause.')
    next=item.trade?.legacy_position_id?t('זו פוזיציה מיובאת; אין להשלים היסטוריית כניסה או תוצאה שחסרה.','This is imported; missing entry history or outcomes are not reconstructed.'):t('התוצאה מוצגת לפי החלקים שמומשו והחלק שנותר פתוח, לא כתשואת תיק.','Outcomes reflect exited portions and the remaining open portion, not portfolio return.')
  }else if(item.state==='waiting'&&entryPriceWait(item.signal,linkedItemOrders(item))){
    next=t('הפקודה ממשיכה להמתין בתוך התוקף המקורי. רק מחיר חדש מנר מאוחר שהושלם ועובר את כל הבקרות יוכל לפתוח פוזיציה; אין הבטחת ביצוע.','The order keeps waiting within its original validity. Only a new price from a later completed candle passing all gates can open a position; execution is not guaranteed.')
  }else if(!reasons.length && item.state==='waiting'){
    title=activityStatusLabel(item,he)
    detail=item.signal?.status==='PENDING_CLOSE'?t('נשמרה בקשת יציאה ממתינה, לא יציאה שבוצעה. אין להסיק שהפוזיציה נסגרה.','A pending exit request is retained, not an executed exit. Position closure is not inferred.'):item.station==='order'?t('פקודה ממתינה נשמרה, אך לא נמצא ביצוע כניסה מקושר. אין להסיק שמחיר הכניסה לא נגע רק מסטטוס ממתין.','A pending order is retained but no entry fill is linked. Pending status alone does not prove that price never touched entry.'):t('הסיגנל נשמר, אך טרם נמצא ביצוע מקושר במדגם.','The signal is retained, but a linked execution is not present in this sample.')
    next=item.signal?.status==='PENDING_CLOSE'?t('ניהול הפוזיציה נפרד מבקשת היציאה. רק ביצוע יציאה מקושר מוכיח שהיתרה נסגרה.','Position management is separate from the exit request. Only a linked exit fill proves that the remainder closed.'):t('הביצוע כפוף למחיר תקף, נר שהושלם ותוקף הפקודה. עד לביצוע זו אינה פוזיציה פעילה.','Execution requires a valid price, completed candle and valid order. Until a fill, this is not an active position.')
  }else if(item.reason==='close_order_invalid')next=t('הפקודה הזאת אינה ממתינה לביצוע ולא בוצעה ממנה יציאה. רק מילוי יציאה מקושר מוכיח סגירה; מצב הפוזיציה נבדק בנפרד.','This order is no longer waiting for execution and performed no exit. Only a linked exit fill proves closure; position state is checked separately.')
  else if(item.reason==='close_order_expired')next=t('אין ביצוע יציאה אוטומטי בדיעבד מהפקודה שפגה. רק מילוי יציאה מקושר מוכיח סגירה; מצב הפוזיציה נבדק בנפרד.','The expired order does not execute an exit retrospectively. Only a linked exit fill proves closure; position state is checked separately.')
  else if(item.reason==='close_recovery_uncertain')next=t('הפקודה נשארת חסומה עד בירור ביצוע היציאה. אין להסיק סגירה עד שהמילוי והקישור לפוזיציה אומתו.','The order stays blocked pending review of exit execution. Closure is not inferred until the fill and position link are verified.')
  else if(item.state==='uncertain')next=t('אין להציג פוזיציה פעילה עד שהביצוע והקשר לפוזיציה הוכרעו ואומתו.','An active position is not displayed until execution and its trade link are resolved and verified.')
  else if(item.kind==='signal'&&item.state==='blocked')next=t('הסיגנל נשמר, אך לא הופעלה ממנו פוזיציה חדשה. חסימת ביצוע אינה מדד לאיכות הסיגנל.','The signal was retained but did not activate a new position. Execution blocks are not signal-quality scores.')
  else if(item.state==='closed')next=t('מצב סופי אינו בקשת כניסה חדשה. אין החייאה של הפקודה מהתצוגה.','A terminal state is not a new entry request. The view cannot revive an order.')
  else if(reasons.length && reasonDefinition(codes[0]).kind==='processing')next=t('נדרשת בדיקה תקינה חדשה. כשל העיבוד עצמו אינו אישור כניסה או החלטת SELL.','A valid new check is required. Processing failure itself is not entry approval or a SELL decision.')
  const facts:Explanation['facts']=[]
  const fact=(label:string,v:unknown,suffix='')=>{const n=finite(v);if(n!=null)facts.push({label,value:n.toFixed(2)+suffix})}
  if(codes.some(c=>reasonKey(c)==='ai_confidence_below_threshold')){
    fact(t('ציון מודל לא מכויל שנשמר','Retained uncalibrated model score'),ai?.confidence)
    fact(t('סף ציון שנשמר בבדיקה','Score threshold retained for the check'),ai?.confidence_threshold)
  }
  if(codes.some(c=>reasonKey(c)==='ai_news_relevance_below_threshold')){
    fact(t('רלוונטיות שנשמרה','Retained relevance'),ai?.news_relevance)
    fact(t('סף רלוונטיות שנשמר','Retained relevance threshold'),ai?.relevance_threshold)
  }
  if(check){
    facts.push(...targetFacts(check,he))
    if(reasonKey(item.reason)==='no_fresh_quote')fact(t('גיל המחיר שנשמר בשניות','Retained quote age in seconds'),check.quote?.age_seconds)
    if(codes.some(c=>['entry_not_above_completed_high','completed_high_unavailable'].includes(reasonKey(c))))
      fact(t('שיא סשנים שהושלמו שנשמר','Retained completed-session high'),check.source_inputs?.completed_high)
  }
  if(item.kind==='position')fact(t('יתרה מהפוזיציה','Position remaining'),item.outcome?.remaining_pct,'%')
  const priceWait=item.state==='waiting'?entryPriceWait(item.signal,linkedItemOrders(item)):null
  if(priceWait)fact(t('מחיר שנבדק ולא אושרה בו כניסה','Checked price with no entry approval'),priceWait.price)
  const modelReason=item.kind==='candidate'&&item.station==='ai'&&typeof ai?.reason==='string'&&ai.reason.trim()?ai.reason.slice(0,800):null
  return {title,detail,next,reasons,facts,modelReason}
}
