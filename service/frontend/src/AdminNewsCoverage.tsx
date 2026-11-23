import { opsTime, type NewsObservation } from './adminSystemModel'

const labels: Record<string, string> = {
  pending: 'בהמתנה לעיבוד', analyzed: 'נותחו', translated: 'תורגמו', duplicate: 'כפילות',
  error: 'כשל עיבוד', stale: 'התיישנו', filtered: 'סוננו', disabled: 'כבוי', other: 'אחר',
  queued_in_window: 'נכנסו לתור', acknowledged: 'שליחה אושרה', awaiting_ack: 'ממתינות לאישור',
  failed: 'נכשלו', cancelled: 'בוטלו', discovered: 'נקלטו מ־SEC', processed: 'עובדו',
  delivery_stopped: 'השליחה נעצרה', processed_without_notice: 'עובדו בלי הודעה בתור',
  identity_unverified: 'זהות לא אומתה', insufficient_information: 'מידע חסר',
  quality_failed: 'לא עברו בקרת איכות', stale_content: 'תוכן התיישן',
  news_pipeline_fenced: 'מסלול פרסום חסום', company_report_requires_structured_filing: 'אין דוח מובנה',
  disabled_by_configuration: 'כבוי בהגדרות', missing_credentials: 'ללא הרשאות יעד',
  news_cutover_fence: 'מעבר בין מסלולים', canonical_safety_rollback: 'חזרה למסלול קודם',
  market_news: 'חדשות שוק', stock_news: 'חדשות מניות', watchlist_news: 'מניות במעקב',
  position_news: 'חדשות פוזיציות', watchlist_news_correction: 'תיקוני מעקב', correction: 'תיקונים',
  trump_truth_post: 'טראמפ', sec_intelligence: 'דיווחי SEC ותוצאות', ownership_activity: 'תנועות פנים',
  buyback_activity: 'רכישות עצמיות', analyst_update: 'עדכוני אנליסטים', company_report: 'דיווחי חברות',
  portfolio_watchlist: 'תיק ומעקב', important_stock_news: 'חדשות מניות חשובות',
  received: 'התקבלו', ingested: 'נשמרו', rejected_assignment: 'שיוך לא אומת', rejected_date: 'תאריך נדחה',
}

function countsLine(counts: Record<string, number>, fields = Object.keys(counts)) {
  return fields.map(field => `${labels[field] ?? 'אחר'} ${counts[field] ?? 0}`).join(' · ')
}

export function AdminNewsCoverage({ data, retained }: { data?: NewsObservation; retained: boolean }) {
  if (!data || data.status !== 'observed') {
    return <section className="ops-infrastructure"><h2>חדשות וכיסוי דוחות</h2><p>המדידה אינה זמינה כרגע.</p></section>
  }
  const { sources, delivery, earnings } = data
  return <section className="ops-infrastructure" aria-label="חדשות וכיסוי דוחות">
    <h2>חדשות וכיסוי דוחות</h2>
    <p>{retained ? 'נתונים שמורים · ' : ''}תצפית מ־<bdi>{opsTime(data.observed_at)}</bdi> · שעון ישראל</p>
    <div className="ops-stage-cards">
      <details className="ops-card">
        <summary><h3>קליטה ועיבוד לפי מקור</h3><p>{data.news_hours} השעות האחרונות</p></summary>
        <div className="ops-evidence ops-providers">
          <p>ידיעה אחת יכולה להיקלט מכמה מקורות. אישורי השליחה נספרים רק כשנמצא קשר ישיר לרשומת הידיעה.</p>
          {sources.partial && <p>המדגם חלקי.</p>}
          {!sources.rows.length && <p>אין קליטות שמורות בחלון.</p>}
          {sources.rows.map(row => <div className="ops-provider" key={row.provider}>
            <strong><bdi>{row.provider}</bdi></strong>
            <p>{row.receipts} קליטות · {row.items} ידיעות · {row.linked_acknowledged} ידיעות עם אישור שליחה מקושר</p>
            <p>{countsLine(row.stages)}</p>
            {Object.keys(row.reasons).length > 0 && <p>{countsLine(row.reasons)}</p>}
            {row.latest_check && <small>מוני המקור בבדיקה האחרונה <bdi>{opsTime(row.latest_check.at)}</bdi><br />{countsLine(row.latest_check.counts)}</small>}
          </div>)}
        </div>
      </details>
      <details className="ops-card">
        <summary><h3>תור ואישורי שליחה</h3><p>{data.news_hours} השעות האחרונות</p></summary>
        <div className="ops-evidence ops-providers">
          <p>החלוקה היא לפי מסלול או סוג הודעה שמור. אישור שליחה עשוי להתייחס להודעה שנכנסה לתור לפני החלון.</p>
          {delivery.partial && <p>המדגם חלקי.</p>}
          {!delivery.rows.length && <p>אין תנועות בתור בחלון.</p>}
          {delivery.rows.map(row => <div className="ops-provider" key={`${row.basis}:${row.route}`}>
            <strong>{labels[row.route]} · {row.basis === 'canonical_route' ? 'מסלול שמור' : 'סוג הודעה'}</strong>
            <p>{countsLine(row.counts, ['queued_in_window', 'acknowledged', 'awaiting_ack', 'failed', 'cancelled', 'disabled'])}</p>
            {Object.keys(row.reasons).length > 0 && <p>{countsLine(row.reasons)}</p>}
          </div>)}
        </div>
      </details>
      <details className="ops-card">
        <summary><h3>דוחות רשמיים לחברות במעקב</h3><p>{data.report_days} הימים האחרונים</p></summary>
        <div className="ops-evidence ops-providers">
          <p>ספירה לפי דוחות 10-Q ו־10-K ותיקוניהם שנקלטו אצלנו. מניות של אותה חברה עשויות להציג אותו דוח. אישור שליחה מקושר לפי מזהה הדוח.</p>
          {earnings.partial && <p>המדגם חלקי.</p>}
          {!earnings.rows.length && <p>אין חברות פעילות במעקב.</p>}
          {earnings.rows.map(row => <div className="ops-provider" key={row.ticker}>
            <strong><bdi>{row.ticker}</bdi></strong>
            <p>{row.counts === null ? 'מיפוי ל־SEC לא אומת' : !row.counts.discovered ? 'אין דוח שנקלט אצלנו בחלון' :
              countsLine(row.counts, ['discovered', 'processed', 'acknowledged', 'processed_without_notice', 'awaiting_ack', 'delivery_stopped'])}</p>
            {row.counts !== null && <small>{row.discovery_checked_at ? <>בדיקת SEC אחרונה <bdi>{opsTime(row.discovery_checked_at)}</bdi></> : 'אין בדיקת SEC מתועדת'}</small>}
          </div>)}
        </div>
      </details>
    </div>
  </section>
}
