// Actual website/MiniApp SSR; no target, provider, translation or send.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import * as React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { fixtureDashboard } from './system-activity-fixtures.mjs'

globalThis.fetch = () => { throw new Error('Bilingual independent SSR forbids HTTP') }
const source = 'I will not approve a 5% increase unless Congress agrees.'
const hebrew = 'לא אאשר עלייה של 5% אלא אם הקונגרס יסכים.'
const id = '117500000000000456'
const post = { id: `trump-truth:${id}`, truth_post_id: id, source_kind: 'trump_truth_relay_v1',
  source_verification: 'relay_only', delivery_status: 'sent', truth_url: `https://truthsocial.com/@realDonaldTrump/${id}`,
  relay_url: 'https://t.me/realdonaldtrump_truth/456', source_excerpt: source,
  translation_status: 'translated', text_he: hebrew, original_published_at: null,
  relay_published_at: '2026-10-22T15:00:00Z', observed_at: '2026-10-22T15:01:00Z',
  sent_at: '2026-10-22T15:02:00Z', is_repost: false, has_media: false,
  media: { status: 'unavailable', kind: null } }
const archive = { version: 1, status: 'READY', generated_at: '2026-10-22T15:03:00Z', items: [post], next_cursor: null }
const bundle = await build({ entryPoints: ['src/ScannerDashboard.tsx', 'src/TrumpTruthNews.tsx'], outdir: 'unused',
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react/jsx-runtime', 'react-router-dom'], loader: { '.png': 'dataurl' },
  plugins: [{ name: 'bilingual-isolated-app', setup(b) {
    b.onResolve({ filter: /^\.\/appShared$/ }, () => ({ path: 'shared', namespace: 'fixture' }))
    b.onResolve({ filter: /^\.\/appChrome$/ }, () => ({ path: 'chrome', namespace: 'fixture' }))
    b.onResolve({ filter: /\.css$/ }, () => ({ path: 'css', namespace: 'fixture' }))
    b.onLoad({ filter: /.*/, namespace: 'fixture' }, a => ({ contents: a.path === 'shared'
      ? "export const API_ORIGIN='http://isolated.invalid';export const useLanguage=()=>({language:globalThis.__QA_BILINGUAL_LANG__})"
      : a.path === 'chrome' ? 'export const TopbarControls=()=>null' : '' }))
  } }] })
const require = createRequire(import.meta.url)
function load(name, injected) {
  let consumed = false
  const module = { exports: {} }
  const react = { ...React, useState(initial) {
    if (injected && !consumed && initial === null) { consumed = true; return React.useState(injected) }
    if (injected && initial === 'all') return React.useState('unrelated_financial_filter')
    return React.useState(initial)
  } }
  new Function('require', 'module', 'exports', bundle.outputFiles.find(f => f.path.endsWith(`${name}.js`)).text)(
    n => n === 'react' ? react : require(n), module, module.exports)
  return module.exports
}
const { TrumpTruthNewsView, parseTruthArchive } = load('TrumpTruthNews')
const withoutClosedDetails = html => html.replace(/<details(?![^>]*\bopen(?:\s|=|>))[^>]*>[\s\S]*?<\/details>/g, '')
const view = (raw, he) => renderToStaticMarkup(React.createElement(TrumpTruthNewsView, { he, data: parseTruthArchive(raw) }))
let assertions = 0
function check(value, description) { assert.ok(value, description); assertions++ }

for (const language of ['he', 'en']) for (const route of ['/market?tab=news', '/market?tab=news&miniapp=1']) {
  globalThis.__QA_BILINGUAL_LANG__ = language
  const data = { ...fixtureDashboard, settings: {}, primary_user: {}, news: [], news_meta: {}, news_watchlist: [], trump_truth: archive }
  const { ScannerDashboard } = load('ScannerDashboard', data)
  const html = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [route] }, React.createElement(ScannerDashboard, { token: null })))
  const visible = withoutClosedDetails(html)
  check(visible.includes(source), `${route}/${language}: exact source excerpt is visible without opening a control`)
  check(visible.includes(hebrew), `${route}/${language}: whole approved Hebrew remains visible`)
  check(visible.includes(post.truth_url) && visible.includes(post.relay_url), 'both source links preserved')
  check(visible.includes('lang="he" dir="rtl"') && visible.includes('lang="en" dir="ltr"'), 'independent directions do not depend on UI language')
}

for (const he of [true, false]) for (const status of ['unavailable', 'not_retained']) {
  const visible = withoutClosedDetails(view({ ...archive, items: [{ ...post, translation_status: status, text_he: null }] }, he))
  check(visible.includes(source) && !visible.includes(hebrew), 'missing translation preserves genuine source but invents no Hebrew')
  check(visible.includes('זמין') && /unavailable|not retained/i.test(visible), 'translation status is explicitly bilingual')
}
for (const status of ['link_only', 'media_only']) {
  const html = view({ ...archive, items: [{ ...post, source_excerpt: '', translation_status: status, text_he: null, has_media: true }] }, true)
  check(!html.includes(source) && !html.includes(hebrew), 'empty source cannot acquire invented English or Hebrew')
  check(html.includes(post.truth_url) && /No |unavailable|without/i.test(html), 'source-empty fallback remains truthful in both languages')
}
const hostile = view({ ...archive, items: [{ ...post, source_excerpt: '<script>not a real script</script>' }] }, true)
check(!hostile.includes('<script>') && hostile.includes('&lt;script&gt;'), 'literal source remains escaped, never interpreted')
console.log(`Independent bilingual website/MiniApp SSR: ${assertions} assertions passed; no live/pixel proof.`)
