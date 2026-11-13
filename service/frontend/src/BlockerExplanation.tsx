import { explainActivity } from './activityExplanation'
import type { ActivityItem } from './systemActivityModel'
/** No requests or actions: readable facts and limits of the retained evidence. */
export function ActivityExplanation({item,he,hideDiscovery=false}:{item:ActivityItem;he:boolean;hideDiscovery?:boolean}) {
  const e=explainActivity(item,he),t=(a:string,b:string)=>he?a:b
  const facts=hideDiscovery?e.facts.filter(f=>f.label!==t('מסלולים מזהים, עשויים לחפוף','Detecting routes, may overlap')):e.facts
  return <section className="activity-explanation" aria-label={t('הסבר המצב','Status explanation')}>
    <strong className="activity-explanation-title">{e.title}</strong>
    <p>{e.detail}</p>
    {e.modelReason&&<div className="activity-model-explanation"><strong>{t('נימוק המודל שנשמר','Retained model explanation')}</strong><blockquote dir="auto">{e.modelReason}</blockquote><small>{t('בשפת המקור; הסבר המודל אינו עובדה מאומתת או המלצה חדשה.','In the retained language; the model explanation is not a verified fact or new recommendation.')}</small></div>}
    {e.reasons.length>1 && <ul className="activity-extra-reasons" aria-label={t('חסמים נוספים שנשמרו','Additional retained blockers')}>
      {e.reasons.slice(1).map(r=><li key={r.code}><strong>{r.title}</strong><p>{r.detail}</p></li>)}
    </ul>}
    {!!facts.length && <dl className="activity-reason-facts">{facts.map(f=><div key={f.label}><dt>{f.label}</dt><dd><bdi>{f.value}</bdi></dd></div>)}</dl>}
    <p className="activity-next"><strong>{t('מה המשמעות להמשך?','What happens next?')}</strong><span>{e.next}</span></p>
  </section>
}
