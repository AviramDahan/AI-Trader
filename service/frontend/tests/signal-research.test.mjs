// Render the actual research view. Synthetic fixtures only; no HTTP or AI.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync, writeFileSync } from 'node:fs'

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
const invalidSummary = render({ data: { ...referenceData, records: [{ ...referenceData.records[0], rejection: 'pre_invalid_rounded_levels' }] } })
assert.ok(/<small>[^<]*מרווח ההתנגדות משאיר את היעד בכניסה או מתחתיה/.test(invalidSummary))
assert.ok(!invalidSummary.includes('רמות לא תקינות אחרי עיגול'))
const unknownDetail = render({ data: { ...referenceData, records: [{ ...referenceData.records[0],
  rejection: 'pre_invalid_rounded_levels', target_checks: [{ ...referenceData.records[0].target_checks[0], rejection_detail: ['unknown_future_code'] }] }] } })
assert.ok(unknownDetail.includes('רמות הכניסה, הסטופ או היעד אינן תקינות'))
for (const reason of ['pre_insufficient_confirmed_price_zones','pre_price_structure_fails_risk_reward']) {
  const labels = render({ data: { ...data, records: [{ ...data.records[0], rejection: reason }] } })
  assert.ok(!new RegExp(`<small>[^<]*${reason}`).test(labels))
}
const conflictingDetail = render({ data: { ...referenceData, records: [{ ...referenceData.records[0],
  rejection: 'pre_no_forward_zone' }] } })
assert.ok(/<small>[^<]*אין אזור התנגדות קדמי/.test(conflictingDetail))
const historyBundle = await build({ entryPoints: ['src/HistoryCacheStatus.tsx'], bundle: true, write: false,
  platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react/jsx-runtime'] })
const historyMod = { exports: {} }
new Function('require', 'module', 'exports', historyBundle.outputFiles[0].text)(createRequire(import.meta.url), historyMod, historyMod.exports)
const cacheView = cache => renderToStaticMarkup(createElement(historyMod.exports.HistoryCacheStatus, { he: true, cache }))
const partialCache = cacheView({ status: 'partial_fallback', age_seconds: 18000, expected_session: '2026-10-07',
  current_symbols: 518, requested_symbols: 520, lagging_symbols: ['PSKY','WBD'], lagging_symbol_count: 2,
  refresh_error_code: 'incomplete_refresh', refresh_error_type: 'RuntimeError', refresh_received_symbols: 0, refresh_requested_symbols: 2 })
assert.ok(partialCache.includes('נתונים עדכניים עם חוסרים נקודתיים'))
assert.ok(partialCache.includes('518/520') && partialCache.includes('<bdi>PSKY, WBD</bdi>'))
assert.ok(partialCache.includes('הספק לא החזיר כיסוי מלא לריענון') && partialCache.includes('0/2'))
assert.ok(!cacheView(undefined).includes('0.0h'))
assert.ok(cacheView({ status: 'stale_fallback' }).includes('נתונים היסטוריים ישנים'))
// The generic mobile dashboard hides tables that have card alternatives.
// Research tables have no such duplicate view and must remain scrollable.
const styles = readFileSync('src/index.css', 'utf8')
assert.match(styles, /\.signal-research \.scanner-table-wrap\s*\{[^}]*display:\s*block;[^}]*max-width:\s*100%;/)
assert.ok(outcomes.includes('scanner-table-wrap') && outcomes.includes('Native'))
const breakout = render({ data: { ...data, rejection_stages: { targets: 1 },
  records: [{ ...data.records[0], rejection: 'pre_entry_not_above_completed_high' }] } })
assert.ok(/<small>[^<]*מחיר הכניסה אינו מעל שיא 20 הסשנים שהושלמו/.test(breakout))
assert.ok(breakout.includes('מבנה / יעד / RR'))
const secRow = { ...data.records[0], sec_decision: { mode: 'paper', baseline_rank_score: .8,
  enhanced_rank_score: .8, sec_adjustment: 0, evidence_status: 'UNKNOWN_NO_RETAINED_EVIDENCE' },
  ai_decision: { action: 'HOLD', confidence: .75, news_relevance: .8, filter_failures: ['ai_hold'],
    reason: '<script>untrusted</script> Synthetic explanation' } }
const noSec = render({ data: { ...data, records: [secRow] } })
assert.ok(noSec.includes('מצב הפעלת SEC') && noSec.includes('אין ראיית SEC שמורה מספקת'))
assert.ok(!noSec.includes('ראיית SEC בהחלטה:'))
assert.ok(noSec.includes('הסבר המודל, לא עובדה מאומתת') && noSec.includes('dir="auto"'))
assert.ok(noSec.includes('&lt;script&gt;untrusted&lt;/script&gt;') && !noSec.includes('<script>untrusted'))
const retainedSec = render({ data: { ...data, records: [{ ...secRow, sec_decision: {
  ...secRow.sec_decision, evidence_status: 'RETAINED_EVIDENCE', ranking_changed_in_paper: false } }] } })
assert.ok(retainedSec.includes('נשמרו תמונת מידע והפניות SEC בהחלטה') && retainedSec.includes('אין שינוי דירוג מתועד'))
const adjustedSec = render({ data: { ...data, records: [{ ...secRow, sec_decision: {
  ...secRow.sec_decision, evidence_status: 'RETAINED_EVIDENCE', ranking_changed_in_paper: true } }] } })
assert.ok(adjustedSec.includes('הדירוג השתנה במסלול PAPER'))
assert.ok(render({ data: referenceData }).includes('לא זמין: לא נשמר הסבר מתאים להצגה.'))
assert.ok(cacheView({ missing_symbol_count: 1, missing_symbols: ['TEST'], requested_symbols: 518 }).includes('חוסר ללא אבחון מפורט נשאר לא ידוע'))
const shortHistory = cacheView({ history_gap_details: { TEST: {
  reason: 'insufficient_completed_history', completed_bars: 8, required_bars: 65 } } })
assert.ok(shortHistory.includes('היסטוריה קצרה מדי לניתוח טכני') && shortHistory.includes('8/65'))
const optionalNewsData={...data,records:[{...data.records[0],rejection:'ai_hold',
  ai_decision:{action:'HOLD',confidence:.85,news_relevance:null,news_sentiment:null,
    news_context:{mode:'price_context',availability:'NO_ELIGIBLE_STORIES'}}}]}
for(const he of [true,false]){
  const html=render({he,data:optionalNewsData})
  assert.ok(html.includes(he?'לא נמדדה; לא נמצאו כתבות בתוקף':'Not measured; no eligible stories'))
  assert.ok(!html.includes('NaN'))
}
console.log('Signal research, evidence, explanation and history rendering assertions passed')
if (process.env.RESEARCH_PREVIEW_HTML) {
  // Optional disposable visual-QA artifact. Real component/CSS, synthetic data;
  // no app server, production connection, React effect, worker or AI request.
  const preview = { ...data, counts: { ...data.counts, candidate_observations: 2, unique_tickers: 2,
      target_pass: 1, ai_attempted: 1, ai_attempt_records: 1, ai_validated: 1 },
    rejection_reasons: { pre_entry_not_above_completed_high: 1, ai_hold: 1 },
    rejection_stages: { targets: 1, ai_filter: 1 }, quote_context: {}, records: [
      { ...data.records[0], ticker: 'CHECK', company: 'מועמדת סינתטית שנפסלה', rejection: 'pre_entry_not_above_completed_high',
        target_checks: [{ ...data.records[0].target_checks[0], rejection_reason: 'entry_not_above_completed_high',
          geometry: { stop_rounded: 97 }, quote: { price: 100, as_of: '2026-10-07T14:00:00Z' },
          source_inputs: { data_as_of: '2026-10-06', zones: [] } }] },
      { ...secRow, ticker: 'TEST', company: 'מועמדת סינתטית בהמתנה', rejection: 'ai_hold', ai_attempts: 1,
        target_checks: [{ ...data.records[0].target_checks[0], outcome: 'PASS',
          geometry: { stop_rounded: 97, target_rounded: 106, nearest_resistance: { low: 106.5 } },
          quote: { price: 100, as_of: '2026-10-07T14:00:00Z' }, source_inputs: { data_as_of: '2026-10-06', zones: [] },
          accepted_levels: { stop: 97, active_target: 106, rr: [2] } }],
        ai_decision: { ...secRow.ai_decision, reason: 'הראיות הסינתטיות אינן מספיקות לכניסה. TEST נשארת בהמתנה.' } }] }
  writeFileSync(process.env.RESEARCH_PREVIEW_HTML,
    `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Isolated research QA</title><style>${styles}</style></head><body><main style="padding:16px;max-width:1050px;margin:auto"><p>נתוני בדיקה סינתטיים בלבד; ללא חיבור למערכת.</p>${render({ data: preview })}${shortHistory}</main></body></html>`)
}
