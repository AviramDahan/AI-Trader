// Actual React view; synthetic aggregate results, no HTTP effects or trading.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync, writeFileSync } from 'node:fs'

const bundle = await build({ entryPoints: ['src/StrategyPerformance.tsx'], bundle: true,
  write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react/jsx-runtime'], plugins: [{ name: 'no-http', setup(b) {
    b.onResolve({ filter: /^\.\/appShared$/ }, () => ({ path: 'stub', namespace: 'stub' }))
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: "export const API_ORIGIN='http://isolated.invalid'" }))
  } }] })
const mod = { exports: {} }
new Function('require','module','exports',bundle.outputFiles[0].text)(createRequire(import.meta.url),mod,mod.exports)
const { StrategyPerformanceView } = mod.exports
const ids = ['BASELINE','VCP_BASE_CONTRACTION','STOCKBEE_MOMENTUM_BURST','PEAD',
  'TREND_PULLBACK_RECLAIM','RELATIVE_STRENGTH_LEADER','UNATTRIBUTED']
const counts = { signals: 1, pending_entry_orders: 1, actual_entries: 0, open_trades: 0,
  fully_closed_trades: 0, partial_exit_trades: 0 }
const metrics = { verified_closed: 0, closed_win_rate: null, mean_closed_net_pct: null,
  expectancy_net_r: null, profit_factor: null, profit_factor_status: 'DATA_INSUFFICIENT' }
const data = { version: 1, as_of: '2026-10-07T16:00:00Z', window_since: '2026-10-05T16:00:00Z',
  coverage: { status: 'COMPLETE_RETAINED_COHORT', clipped: [], evidence_gaps: {} },
  overall: { counts, metrics }, strategy_rows: ids.map(strategy_id => ({ strategy_id, counts, metrics,
    enabled: strategy_id === 'UNATTRIBUTED' ? null : strategy_id !== 'PEAD', non_additive: true })),
  exact_set_groups: [{ strategy_ids: ['BASELINE','STOCKBEE_MOMENTUM_BURST'], counts, metrics }],
  excluded_cohorts: { Legacy: { trades: 1 }, Shadow: { trades: 1 } } }
const render = changes => renderToStaticMarkup(createElement(StrategyPerformanceView, { he: true, data, ...changes }))
const empty = render({})
assert.ok(empty.includes('ביצועי מסלולי כניסה') && empty.includes('dir="rtl"'))
for (const label of ['מסלול הבסיס','התכווצות בסיס','התפרצות מומנטום','המשך תנועה אחרי דוחות',
  'תיקון וחזרה למגמה','מובילת חוזק יחסי','רשומות ללא מקור מאומת']) assert.ok(empty.includes(label))
assert.ok(empty.includes('גילוי מוגדר ככבוי') && empty.includes('גילוי מוגדר כמופעל'))
assert.ok(empty.includes('לא אישור לפתוח פוזיציה'))
assert.ok(empty.includes('טרם ניתן לחשב') && !empty.includes('0.00R') && !empty.includes('0.00%'))
assert.ok(empty.includes('פקודה ממתינה אינה עסקה') && empty.includes('אין לחבר את המספרים'))
assert.ok(empty.includes('אינו תשואת תיק') && empty.includes('Shadow אינו חשבון הון עצמאי'))
assert.ok(empty.includes('מקור של סיגנל SELL שסגר עסקה לא מחליף את מקור הכניסה'))
assert.ok(empty.includes('Profit Factor') && !empty.includes('Infinity') && !empty.includes('NaN'))
const winner = { ...data.strategy_rows[0], counts: { ...counts, actual_entries: 1, fully_closed_trades: 1 },
  metrics: { ...metrics, verified_closed: 1, closed_win_rate: 1, mean_closed_net_pct: 1.2,
    expectancy_net_r: .5, profit_factor_status: 'UNDEFINED_NO_LOSSES' } }
const win = render({ data: { ...data, strategy_rows: [winner] } })
assert.ok(win.includes('100.00%') && win.includes('1.20%') && win.includes('0.50R'))
assert.ok(win.includes('אינו מוגדר כשאין עסקאות סגורות מפסידות'))
const partial = { ...winner, counts: { ...counts, open_trades: 1, partial_exit_trades: 1 },
  metrics: { ...metrics, open_realized_mean_net_pct: 4.8, open_realized_mean_net_r: .96 } }
const realized = render({ data: { ...data, strategy_rows: [partial] } })
assert.ok(realized.includes('4.80% / 0.96R') && realized.includes('משקל הכמות המקורית'))
const unknown = render({ data: { ...data, coverage: { status: 'PARTIAL' }, strategy_rows: [{ ...winner,
  counts: Object.fromEntries(Object.keys(counts).map(k => [k,null])), metrics: { ...metrics, status: 'PARTIAL_EVIDENCE' } }] } })
assert.ok(unknown.includes('לא ידוע') && unknown.includes('אינו אפס') && unknown.includes('לא משחזרים החלטות חסרות'))
assert.ok(render({ data: null, error: true }).includes('role="alert"'))
assert.ok(render({ data: null }).includes('role="status"'))
assert.ok(render({ he: false }).includes('Entry strategy performance'))
const hostile = render({ data: { ...data, strategy_rows: [{ ...winner, strategy_id: '<script>untrusted</script>' }] } })
assert.ok(hostile.includes('&lt;script&gt;untrusted&lt;/script&gt;') && !hostile.includes('<script>untrusted'))
const styles = readFileSync('src/index.css', 'utf8')
assert.match(styles, /\.strategy-performance-grid[^}]*minmax\(min\(100%, 310px\), 1fr\)/)
assert.match(styles, /@media \(max-width: 600px\)[\s\S]*?\.strategy-performance-grid\s*\{\s*grid-template-columns: minmax\(0,1fr\)/)
assert.ok(readFileSync('src/SignalResearch.tsx','utf8').includes("mode === 'results' && <StrategyPerformance he={he}"))
console.log('Strategy performance real React rendering: unknown, partial, PF, overlap, RTL and mobile CSS assertions passed')
if (process.env.STRATEGY_PERFORMANCE_PREVIEW_HTML) {
  writeFileSync(process.env.STRATEGY_PERFORMANCE_PREVIEW_HTML, `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Isolated strategy performance QA</title><style>${styles}</style></head><body><main style="max-width:1100px;margin:auto;padding:12px"><p>נתוני בדיקה סינתטיים בלבד. אין חיבור למערכת או למסחר.</p>${render({ data: { ...data, strategy_rows: [winner, partial, ...data.strategy_rows.slice(2)] } })}</main></body></html>`)
}
