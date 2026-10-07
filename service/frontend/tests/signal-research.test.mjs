// Render the actual research view. Synthetic fixtures only; no HTTP or AI.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const result = await build({ entryPoints: ['src/SignalResearch.tsx'], bundle: true, write: false,
  platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react/jsx-runtime'],
  plugins: [{ name: 'no-runtime-or-http', setup(b) {
    b.onResolve({ filter: /^\.\/appShared$/ }, () => ({ path: 'stub', namespace: 'stub' }))
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: "export const API_ORIGIN='http://isolated.invalid'" }))
  } }] })
const mod = { exports: {} }
new Function('require', 'module', 'exports', result.outputFiles[0].text)(createRequire(import.meta.url), mod, mod.exports)
const { ResearchView } = mod.exports
const data = {
  window_since: '2026-10-07T05:00:00Z', generated_at: '2026-10-07T16:00:00Z', available_since: null,
  clipped: [], records_clipped: false, counts: { candidate_observations: 3, unique_tickers: 1, exact_reference_configurations: 2, target_pass: 0, ai_attempted: 0, signals_qualified: 0, entries: 0 },
  rejection_reasons: { pre_no_fresh_quote: 3 }, rejection_stages: { quote: 3 }, quote_context: { regular_session: 2, outside_regular_session: 1 },
  execution: { allocation_blocked: 0, fill_rate: null },
  records: [{ scan_id: 'synthetic', ticker: 'TEST', company: '<script>secret</script>', direction: 'BUY', at: '2026-10-07T14:00:00Z', ai_attempts: 0,
    technical_recorded: true, rejection: 'pre_nearest_resistance_below_2r', session: { is_open: true }, reviews: [], signals: [], orders: [],
    target_checks: [{ phase: 'pre_ai', policy_version: 'single_target_v2', outcome: 'REJECT', quote: { price: 100 }, geometry: { stop_rounded: 97, target_rounded: 104, rr_rounded: 1.33, nearest_resistance: { low: 104.5 } }, source_inputs: { zones: [] } }] }],
  outcomes: [], outcome_groups: [{ cohort: 'Native', side: 'long', strategy: 'single', open: 0, closed: 0, verified_closed: 0, mean_net_pct: null, expectancy_net_r: null, win_rate: null }],
}
const render = props => renderToStaticMarkup(createElement(ResearchView, { he: true, data, ...props }))
const research = render({})
assert.ok(research.includes('מחקר סיגנלים'))
assert.ok(research.includes('מחוץ לשעות מסחר רגילות'))
assert.ok(research.includes('1.33R'))
assert.ok(research.includes('role="img"') && research.includes('<bdi>TEST</bdi>'))
assert.ok(research.includes('&lt;script&gt;secret&lt;/script&gt;') && !research.includes('<script>secret'))
const outcomes = render({ mode: 'results' })
assert.ok(outcomes.includes('—'))
assert.ok(!outcomes.includes('NaN') && !outcomes.includes('0.00R') && !outcomes.includes('0.00%'))
assert.ok(outcomes.includes('אינו תשואת תיק') && outcomes.includes('MFE/MAE'))
assert.ok(render({ data: { ...data, clipped: ['technical_details'] } }).includes('פרטי המדגם מוגבלים'))
assert.ok(render({ data: null, error: 'HTTP 503' }).includes('role="alert"'))
const english = render({ he: false, mode: 'summary' })
assert.ok(english.includes('Most common recorded blocker'))
assert.ok(!english.includes('research-candidate'))
console.log('Signal research rendering: 15 assertions passed')
