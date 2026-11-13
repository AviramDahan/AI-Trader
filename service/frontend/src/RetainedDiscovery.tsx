import { targetFacts } from './targetDiagnostics'
import type { Row } from './systemActivityModel'
/** Reuse the validated public check projection; never borrow another scan's source. */
export function RetainedDiscovery({checks,he}:{checks:Row[];he:boolean}) {
  const label=he?'מסלולים מזהים, עשויים לחפוף':'Detecting routes, may overlap'
  const route=[...checks].reverse().flatMap(c=>targetFacts(c,he)).find(f=>f.label===label)
  return <div className="retained-discovery">
    <strong>{he?'מסלולים שזיהו בבדיקה הזאת':'Detecting routes in this check'}</strong>
    <p>{route?.value||(he?'ייחוס מסלול לא נשמר או לא אומת.':'Route attribution was not retained or verified.')}</p>
    {route&&<small>{he?'מסלולים עשויים לחפוף; זיהוי אינו סיגנל מאושר או פקודה נוספת.':'Routes may overlap; discovery is not an approved signal or another order.'}</small>}
  </div>
}
