type Row = Record<string, any>

export const ENTRY_REJECTIONS: Record<string, [string, string]> = {
  fill_rr_below_2: ['יחס הסיכוי־סיכון במחיר הביצוע נמוך מ־2R', 'Execution-price reward/risk is below 2R'],
  fill_outside_plan: ['מחיר הביצוע מחוץ לטווח הסטופ והיעד השמורים', 'Execution price is outside the saved stop/target range'],
  fill_stop_distance_invalid: ['מרחק הסטופ במחיר הביצוע אינו עומד בהגנות', 'Execution-price stop distance fails the safeguards'],
  fill_inside_unresolved_zone: ['מחיר הביצוע בתוך אזור מחיר לא פתור', 'Execution price is inside an unresolved price zone'],
  fill_no_longer_above_completed_high: ['מחיר הביצוע אינו מעל שיא 20 הסשנים שהושלמו', 'Execution price is not above the completed 20-session high'],
  fill_introduces_forward_resistance: ['נמצאה התנגדות קדמית ביחס למחיר הביצוע', 'Execution price introduces forward resistance'],
  fill_changes_nearest_resistance: ['מחיר הביצוע משנה את ההתנגדות הקרובה שנבדקה', 'Execution price changes the checked nearest resistance'],
  order_plan_mismatch: ['תוכנית הפקודה אינה תואמת לתוכנית שנשמרה', 'Order plan does not match the saved contract'],
  order_levels_mismatch: ['רמות הפקודה אינן תואמות לרמות שנשמרו', 'Order levels do not match the saved levels'],
  single_policy_contract_mismatch: ['תוכנית היעד היחיד אינה תואמת לחוזה שנשמר', 'Single-target plan does not match the saved contract'],
  breakout_policy_contract_mismatch: ['תוכנית הפריצה אינה תואמת לחוזה שנשמר', 'Breakout plan does not match the saved contract'],
  unsupported_single_policy: ['חוזה היעד היחיד אינו נתמך', 'Single-target contract is unsupported'],
  unsupported_breakout_policy: ['חוזה הפריצה אינו נתמך', 'Breakout contract is unsupported'],
}

export function entryRejectionCode(signal: Row | undefined, orders: Row[] = []): string | null {
  if (signal?.status !== 'ENTRY_POLICY_REJECTED') return null
  const direct = signal.entry_rejection_reason
  if (typeof direct === 'string' && Object.prototype.hasOwnProperty.call(ENTRY_REJECTIONS, direct)) return direct
  if (signal.id == null) return null
  const entry = orders.filter(o => o.signal_id != null && String(o.signal_id) === String(signal.id) &&
    o.purpose === 'entry' && o.status === 'invalid').sort((a,b) => Number(a.id)-Number(b.id))[0]
  const code = entry?.entry_rejection_reason
  return typeof code === 'string' && Object.prototype.hasOwnProperty.call(ENTRY_REJECTIONS, code) ? code : null
}

export function entryRejectionLabel(code: string | null, he: boolean): string {
  return code && Object.prototype.hasOwnProperty.call(ENTRY_REJECTIONS, code) ? ENTRY_REJECTIONS[code][he?0:1] :
    he ? 'פירוט הסיבה לא נשמר או אינו מוכר; אין לנחש את הסיבה' : 'Reason detail was not retained or is unrecognized; do not infer it'
}

export function activeTargetIndexes(record: Row): number[] {
  if (['single_target_v2','single_breakout_v1'].includes(record.policy_version)) return record.tp1 == null ? [] : [1]
  return [1,2,3].filter(i => record[`tp${i}`] != null && Number(record[`operational_tp${i}_pct`] ?? record[`tp${i}_pct`] ?? 0) > 0)
}

export function positionMove(trade: Row): number | null {
  if (trade.status !== 'open') return null
  const price = trade.current_price ?? trade.last_price
  const entry = trade.entry_price
  if (price == null || entry == null || !Number.isFinite(Number(price)) || !Number.isFinite(Number(entry)) || Number(price) <= 0 || Number(entry) <= 0) return null
  return (trade.side === 'short' ? -1 : 1) * (Number(price) / Number(entry) - 1) * 100
}

export function unifiedSignals(signals: Row[], trades: Row[], active: (row: Row) => boolean) {
  const main = trades.filter(t => !t.is_shadow)
  const linked = new Set(main.map(t => t.signal_id).filter(id => id != null).map(String))
  return {
    open: main.filter(t => t.status === 'open'),
    closed: main.filter(t => t.status !== 'open'),
    waiting: signals.filter(s => active(s) && !linked.has(String(s.id))),
    history: signals.filter(s => !s.legacy_unverified && !active(s) && !linked.has(String(s.id))),
  }
}
