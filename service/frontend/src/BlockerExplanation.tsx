import { explainActivity } from './activityExplanation'
import type { ActivityItem } from './systemActivityModel'
/** No requests or actions: readable facts and limits of the retained evidence. */
export function ActivityExplanation({item,he}:{item:ActivityItem;he:boolean}) {
  const e=explainActivity(item,he),t=(a:string,b:string)=>he?a:b
  return <section className="activity-explanation" aria-label={t('הסבר המצב','Status explanation')}>
    <strong className="activity-explanation-title">{e.title}</strong>
    <p>{e.detail}</p>
    {e.modelReason&&<div className="activity-model-explanation"><strong>{t('נימוק המודל שנשמר','Retained model explanation')}</strong><blockquote dir="auto">{e.modelReason}</blockquote><small>{t('בשפת המקור; הסבר המודל אינו עובדה מאומתת או המלצה חדשה.','In the retained language; the model explanation is not a verified fact or new recommendation.')}</small></div>}
    {e.reasons.length>1 && <ul className="activity-extra-reasons" aria-label={t('חסמים נוספים שנשמרו','Additional retained blockers')}>
      {e.reasons.slice(1).map(r=><li key={r.code}><strong>{r.title}</strong><p>{r.detail}</p></li>)}
    </ul>}
    {!!e.facts.length && <dl className="activity-reason-facts">{e.facts.map(f=><div key={f.label}><dt>{f.label}</dt><dd><bdi>{f.value}</bdi></dd></div>)}</dl>}
    <p className="activity-next"><strong>{t('מה המשמעות להמשך?','What happens next?')}</strong><span>{e.next}</span></p>
  </section>
}
