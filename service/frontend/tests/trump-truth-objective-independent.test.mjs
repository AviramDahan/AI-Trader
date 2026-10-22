// Independent synthetic SSR: actual NEWS route and public presentation only.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import * as React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { fixtureDashboard } from './system-activity-fixtures.mjs'

globalThis.fetch = () => { throw new Error('Independent SSR forbids HTTP') }
let checks = 0
const check = (value, description) => { assert.ok(value, description); checks++ }
const id = '117500000000000123', text = 'לא נאשר תוספת של 5% בלי הסכמת הקונגרס.'
const post = { id: `trump-truth:${id}`, truth_post_id: id, source_kind: 'trump_truth_relay_v1',
  source_verification: 'relay_only', delivery_status: 'sent',
  truth_url: `https://truthsocial.com/@realDonaldTrump/${id}`, relay_url: 'https://t.me/realdonaldtrump_truth/123',
  source_excerpt: 'We will not approve a 5% increase without Congress.',
  translation_status: 'translated', text_he: text, original_published_at: null,
  relay_published_at: '2026-10-22T15:00:00Z', observed_at: '2026-10-22T15:01:00Z',
  sent_at: '2026-10-22T15:02:00Z', is_repost: false, has_media: false, publication_policy: 'original_relay_v1',
  media: { status: 'unavailable', kind: null } }
const archive = { version: 1, status: 'READY', generated_at: '2026-10-22T15:03:00Z',
  items: [post], next_cursor: null }
const bundle = await build({ entryPoints: ['src/ScannerDashboard.tsx', 'src/TrumpTruthNews.tsx'], outdir: 'unused',
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react/jsx-runtime', 'react-router-dom'], loader: { '.png': 'dataurl' },
  plugins: [{ name: 'independent-no-app-network', setup(b) {
    b.onResolve({ filter: /^\.\/appShared$/ }, () => ({ path: 'shared', namespace: 'fixture' }))
    b.onResolve({ filter: /^\.\/appChrome$/ }, () => ({ path: 'chrome', namespace: 'fixture' }))
    b.onResolve({ filter: /\.css$/ }, () => ({ path: 'css', namespace: 'fixture' }))
    b.onLoad({ filter: /.*/, namespace: 'fixture' }, args => ({ contents: args.path === 'shared'
      ? "export const API_ORIGIN='http://isolated.invalid';export const useLanguage=()=>({language:globalThis.__QA_TRUTH_LANG__})"
      : args.path === 'chrome' ? 'export const TopbarControls=()=>null' : '' }))
  } }] })
const require = createRequire(import.meta.url)
const load = (name, injected) => {
  let consumed = false
  const module = { exports: {} }
  const react = { ...React, useState(initial) {
    if (injected && !consumed && initial === null) { consumed = true; return React.useState(injected) }
    if (injected && initial === 'all') return React.useState('not_matching_financial_filter')
    return React.useState(initial)
  } }
  new Function('require', 'module', 'exports', bundle.outputFiles.find(file => file.path.endsWith(`${name}.js`)).text)(
    name => name === 'react' ? react : require(name), module, module.exports)
  return module.exports
}
const { parseTruthArchive, TrumpTruthNewsView } = load('TrumpTruthNews')
const render = (raw, props = {}) => renderToStaticMarkup(React.createElement(TrumpTruthNewsView,
  { he: true, data: parseTruthArchive(raw), ...props }))

for (const language of ['he', 'en']) for (const route of ['/market?tab=news', '/market?tab=news&miniapp=1']) {
  globalThis.__QA_TRUTH_LANG__ = language
  const data = { ...fixtureDashboard, settings: {}, primary_user: {}, news: [], news_meta: {}, news_watchlist: [], trump_truth: archive }
  const { ScannerDashboard } = load('ScannerDashboard', data)
  const html = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [route] },
    React.createElement(ScannerDashboard, { token: null })))
  check(html.includes(text), `actual ${route}/${language} must show the entire approved Hebrew`)
  check(html.includes(post.truth_url) && html.includes(post.relay_url), 'actual route preserves both verified source links')
  check(!html.includes('"fence"') && !html.includes('"binding"'), 'no raw retained envelope is rendered')
}

const normal = render(archive)
check(normal.includes('lang="he" dir="rtl"'), 'Hebrew body keeps explicit language and RTL')
check(normal.includes('לא אומת') && normal.includes('נרשם כנשלח'), 'primary-time and delivery qualifications stay explicit')
check(normal.includes('target="_blank" rel="noopener noreferrer"'), 'source links open safely')
check(normal.includes('שפת המקור') && normal.includes(post.source_excerpt), 'source-language excerpt is separately labelled')

for (const status of ['not_retained', 'unavailable', 'media_only', 'link_only']) {
  const html = render({ ...archive, items: [{ ...post, translation_status: status, text_he: null, has_media: true }] })
  check(!html.includes(text), `${status} does not fabricate a retained translation`)
  check(html.includes(post.truth_url) && html.includes('המדיה אינה זמינה'), 'unavailable source media remains honest with a source link')
}
check(render({ ...archive, items: [{ ...post, translation_status: 'not_retained', text_he: null }] }).includes('אינה משוחזרת'), 'missing cache is not silently reconstructed')

for (const patch of [
  { text_he: { private: 'SYNTHETIC_SECRET' } }, { text_he: ['עברית'] }, { text_he: true },
  { truth_url: 'javascript:alert(1)' }, { relay_url: 'https://t.me/realdonaldtrump_truth.evil/123' },
  { source_verification: 'official_primary' }, { delivery_status: 'sending' }, { id: 123 },
  { sent_at: '2027-01-01T00:00:00Z' }, { original_published_at: post.relay_published_at },
]) {
  check(parseTruthArchive({ ...archive, items: [{ ...post, ...patch }] }).items.length === 0,
    'malformed, private, wrong-source or unsent public data cannot become a card')
}
const extra = { ...post, private_debug: 'SYNTHETIC_SECRET', fence: { token: 'SYNTHETIC_SECRET' },
  attempts: 99, media: { status: 'available', kind: 'photo', asset_token: 'a'.repeat(64), path: '/private/file', bot_url: 'https://api.telegram.org/private' } }
const sanitized = JSON.stringify(parseTruthArchive({ ...archive, items: [extra] }))
for (const forbidden of ['SYNTHETIC_SECRET', '/private/file', 'api.telegram.org', 'private_debug', 'attempts'])
  check(!sanitized.includes(forbidden), 'parser is an allowlist and never carries private extra metadata')
const escaped = render({ ...archive, items: [{ ...post, text_he: '<script>שלום</script>', source_excerpt: '<img src=x onerror=alert(1)>' }] })
check(!escaped.includes('<script>') && !escaped.includes('<img src=x') && escaped.includes('&lt;script&gt;'), 'untrusted excerpts are escaped, not interpreted as markup')

for (const kind of ['photo', 'video']) {
  const html = render({ ...archive, items: [{ ...post, has_media: true,
    media: { version: 'trump_truth_media_v1', status: 'available', kind, asset_token: 'a'.repeat(64),
      mime_type: kind === 'photo' ? 'image/jpeg' : 'video/mp4', bytes: 4 } }] })
  check(html.includes('/api/scanner/trump-media/' + 'a'.repeat(64)), 'media uses only a public opaque same-origin asset endpoint')
  check(!html.includes('autoplay') && !html.includes('api.telegram.org'), 'no automatic video playback or private Bot API source')
}
check(render(null).includes('role="alert"'), 'unknown archive is unavailable, not a verified zero-post census')
check(parseTruthArchive({ ...archive, items: new Array(21).fill(post) }).status === 'UNAVAILABLE', 'public page cap cannot be exceeded')
console.log(`Independent Truth website/MiniApp SSR: ${checks} assertions passed; no HTTP, visual-browser or natural-media claim.`)
