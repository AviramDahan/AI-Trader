// Synthetic fixtures only. Not historical results or live signals.
const at = '2026-10-09T15:00:00Z'
export const candidate = (ticker, changes = {}) => ({ scan_id: `synthetic-${ticker}`, ticker, company: `Synthetic ${ticker}`, at,
  direction: 'BUY', technical_recorded: true, ai_attempts: 0, rejection: null, target_checks: [], reviews: [], signals: [], orders: [], ...changes })
export const fixtureResearch = {
  generated_at: at, window_since: '2026-10-08T15:00:00Z', records_clipped: true, clipped: [],
  records: [
    candidate('ALFA'), candidate('BETA', { target_checks: [{ phase: 'pre_ai', outcome: 'PASS', observed_at: at, policy_version: 'single_target_v2', quote: { price: 100, eligible_for_entry: true }, accepted_levels: { entry: 100, stop: 97, active_target: 106, rr: [2] } }] }),
    candidate('GAMA', { rejection: 'insufficient_current_news', rejection_stage: 'news' }),
    candidate('DELT', { ai_attempts: 1, ai_decision: { action: 'HOLD', confidence: .6 }, rejection: 'ai_hold', rejection_stage: 'ai_filter', reviews: [{ result: 'validated', attempts: 1, at }] }),
    candidate('ECHO', { signals: [{ id: 1, status: 'RISK_BLOCKED' }] }),
    candidate('FOXT', { signals: [{ id: 2, status: 'PENDING_ENTRY' }], orders: [{ id: 12, purpose: 'entry', status: 'pending' }] }),
    candidate('GOLF', { signals: [{ id: 3, status: 'RECOVERY_UNCERTAIN' }], orders: [{ id: 13, purpose: 'entry', status: 'recovery_uncertain' }] }),
    candidate('HOTL', { signals: [{ id: 4, status: 'ENTERED' }], orders: [{ id: 14, purpose: 'entry', status: 'filled' }] }),
    candidate('INDI', { signals: [{ id: 5, status: 'CLOSED' }], orders: [{ id: 15, purpose: 'entry', status: 'filled' }] }),
  ],
  outcomes: [{ trade_id: 40, signal_id: 4, ticker: 'HOTL', cohort: 'Native', remaining_pct: 100, realized_net_pct: -.05, realized_net_r: -.01,
    open_gross_pct: 1, open_gross_r: .2, mark_at: at, exits: [] },
    { trade_id: 50, signal_id: 5, ticker: 'INDI', cohort: 'Native', remaining_pct: 0, realized_net_pct: 5.8, realized_net_r: 1.93,
      open_gross_pct: null, open_gross_r: null, exits: [{ type: 'tp', at, position_pct: 100 }] }],
}
export const fixtureDashboard = {
  market: { is_open: true }, activity: { last_scan_at: Date.parse(at)/1000 },
  signals: [1,2,3,4,5].map((id, index) => ({ id, ticker: ['ECHO','FOXT','GOLF','HOTL','INDI'][index], company: 'Synthetic company',
    action: 'BUY', planned_entry: 100, original_stop: 97, current_stop: 97, tp1: 106, tp2: null, tp3: null,
    policy_version: 'single_target_v2', active_target: 106, rr1: 2, created_at: at, valid_until: '2026-10-10T15:00:00Z',
    status: ['RISK_BLOCKED','PENDING_ENTRY','RECOVERY_UNCERTAIN','ENTERED','CLOSED'][index],
    technical_json: { target_plan: { policy_version: 'single_target_v2', active_target: 106, rr: [2], stop: 97 } } })),
  trades: [{ id: 40, signal_id: 4, ticker: 'HOTL', entry_price: 100, current_stop: 97, status: 'open', is_shadow: 0, opened_at: at,
    tp1: 106, tp2: null, tp3: null, policy_version: 'single_target_v2', settings: { target_plan: { active_target: 106, rr: [2], policy_version: 'single_target_v2' } } },
    { id: 50, signal_id: 5, ticker: 'INDI', entry_price: 100, current_stop: 97, status: 'closed', is_shadow: 0, opened_at: at, closed_at: at },
    { id: 60, signal_id: 4, ticker: 'HOTL', status: 'open', is_shadow: 1 }],
  services: ['scan','monitor','news_feed'].map(component => ({ component, status: 'ok', last_success_at: at })),
}
