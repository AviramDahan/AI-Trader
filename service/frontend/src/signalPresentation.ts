type Row = Record<string, any>

export function positionMove(trade: Row): number | null {
  if (trade.status !== 'open') return null
  const price = trade.current_price ?? trade.last_price
  const entry = trade.entry_price
  if (price == null || entry == null || !Number.isFinite(Number(price)) || !Number.isFinite(Number(entry)) || Number(price) <= 0 || Number(entry) <= 0) return null
  return (Number(price) / Number(entry) - 1) * 100
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
