// Render the actual research view. Synthetic fixtures only; no HTTP or AI.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'

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
const referenceData = { ...data, session_waits: { pre_waiting_regular_session: 9 }, records: [{ ...data.records[0],
  rejection: 'pre_waiting_regular_session', ai_decision: { action: 'HOLD', confidence: .7, news_relevance: .8,
    filter_failures: ['ai_hold', 'ai_confidence_below_threshold'] },
  target_checks: [{ ...data.records[0].target_checks[0], rejection_reason: 'invalid_rounded_levels',
    rejection_detail: ['target_buffer_reaches_entry'], quote: { price: 100, fresh: false, eligible_for_entry: false } }] }] }
const reference = render({ data: referenceData })
assert.ok(reference.includes('המתנה למסחר הרגיל — בנפרד מפסילות איכות'))
assert.ok(reference.includes('מחיר לתצוגת מחקר בלבד; אינו מאשר כניסה.'))
assert.ok(reference.includes('זהו מחיר אחרון ידוע, לא מחיר טרי.'))
assert.ok(reference.includes('מרווח ההתנגדות משאיר את היעד בכניסה או מתחתיה'))
assert.ok(reference.includes('ציון לא מכויל') && reference.includes('ציון המודל מתחת לסף'))
assert.ok(reference.includes('החלטת AI: המתנה'))
assert.ok(!reference.includes('NaN'))
// The generic mobile dashboard hides tables that have card alternatives.
// Research tables have no such duplicate view and must remain scrollable.
const styles = readFileSync('src/index.css', 'utf8')
assert.match(styles, /\.signal-research \.scanner-table-wrap\s*\{[^}]*display:\s*block;[^}]*max-width:\s*100%;/)
assert.ok(outcomes.includes('scanner-table-wrap') && outcomes.includes('Native'))
console.log('Signal research rendering: 24 assertions passed')
