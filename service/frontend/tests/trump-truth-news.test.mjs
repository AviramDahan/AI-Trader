// Actual NEWS route rendering with synthetic public data, no HTTP effects.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import * as React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { fixtureDashboard } from './system-activity-fixtures.mjs'
import { readFileSync, writeFileSync } from 'node:fs'

const post={id:'trump-truth:117500000000000123',source_kind:'trump_truth_relay_v1',source_verification:'relay_only',
  truth_post_id:'117500000000000123',truth_url:'https://truthsocial.com/@realDonaldTrump/117500000000000123',
  relay_url:'https://t.me/realdonaldtrump_truth/123',source_excerpt:'We will not raise tariffs by 5%.',
  translation_status:'translated',text_he:'לא נעלה את המכסים ב־5%.',relay_published_at:'2026-10-22T15:00:00Z',
  observed_at:'2026-10-22T15:01:00Z',sent_at:'2026-10-22T15:02:00Z',original_published_at:null,
  is_repost:false,has_media:false,delivery_status:'sent',media:{status:'unavailable',kind:null}}
const archive={version:1,status:'READY',generated_at:'2026-10-22T15:03:00Z',items:[post],next_cursor:null,coverage:{history_days:7}}
const data={...fixtureDashboard,settings:{},primary_user:{},news:[],news_meta:{},news_watchlist:[],trump_truth:archive}
const bundle=await build({entryPoints:['src/ScannerDashboard.tsx','src/TrumpTruthNews.tsx'],outdir:'unused',bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',
  external:['react','react/jsx-runtime','react-router-dom'],loader:{'.png':'dataurl'},plugins:[{name:'isolated',setup(b){
    b.onResolve({filter:/^\.\/appShared$/},()=>({path:'shared',namespace:'stub'}))
    b.onResolve({filter:/^\.\/appChrome$/},()=>({path:'chrome',namespace:'stub'}))
    b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}))
    b.onLoad({filter:/.*/,namespace:'stub'},a=>({contents:a.path==='shared'?"export const API_ORIGIN='http://isolated.invalid';export const useLanguage=()=>({language:'he'})":a.path==='chrome'?'export const TopbarControls=()=>null':''}))
  }}]})
let inject=true, injectFilters=false
const require=createRequire(import.meta.url), m={exports:{}}
new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith('ScannerDashboard.js')).text)(name=>name==='react'?{...React,
  useState(initial){if(inject&&initial===null){inject=false;return React.useState(data)}if(injectFilters&&initial==='all')return React.useState('not_matching');return React.useState(initial)}}:require(name),m,m.exports)
globalThis.fetch=()=>{throw new Error('no HTTP in rendering test')}
const html=renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/market?tab=news&miniapp=1']},React.createElement(m.exports.ScannerDashboard,{token:null})))
assert.ok(html.includes('חדשות — מהחדש לישן'),'fixture must reach real NEWS view')
assert.ok(html.includes(post.text_he),'actual NEWS view must display approved Hebrew, not omit Trump posts')
assert.ok(html.includes('Truth Social')&&html.includes('דיווח מערוץ מעקב'))
assert.ok(html.includes('שפת המקור')&&html.includes(post.source_excerpt))
assert.ok(!/<details\b[^>]*>[\s\S]*?We will not raise tariffs by 5%\.[\s\S]*?<\/details>/.test(html), 'English source must be visibly present by default, not hidden behind details or a language toggle')
assert.ok(html.includes('lang="en" dir="ltr"') && html.includes('lang="he" dir="rtl"'), 'both content languages must have explicit direction')
assert.ok(html.includes('לא אומת')&&!html.includes('סנטימנט: חיובי'))
assert.ok(html.includes('dir="rtl"')&&html.includes('miniapp-secondary'))
inject=true;injectFilters=true
assert.ok(renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/market?tab=news']},React.createElement(m.exports.ScannerDashboard,{token:null}))).includes(post.text_he),'ordinary financial filters cannot hide relay posts')

const viewModule={exports:{}}
new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith('TrumpTruthNews.js')).text)(require,viewModule,viewModule.exports)
const {parseTruthArchive,TrumpTruthNewsView}=viewModule.exports
const render=(value=archive,props={})=>renderToStaticMarkup(React.createElement(TrumpTruthNewsView,{he:true,data:parseTruthArchive(value),...props}))
for(const he of [true,false]) {
  const both=render(archive,{he})
  assert.ok(both.includes(post.text_he)&&both.includes(post.source_excerpt),'both actual languages visible under either UI language')
  assert.ok(!/<details\b/.test(both),'neither language is collapsed by default')
  assert.equal((both.match(/data-truth-post=/g)||[]).length,1,'two languages must remain one published post')
}
for(const translation_status of ['unavailable','not_retained','media_only','link_only']) {
  const out=render({...archive,items:[{...post,translation_status,text_he:null}]})
  assert.ok(!out.includes(post.text_he)&&out.includes(post.truth_url),'fallback must never invent Hebrew or drop primary link')
  assert.ok(out.includes('lang="he" dir="rtl"')&&out.includes('lang="en" dir="ltr"'))
  assert.ok(out.includes(post.source_excerpt),'actual English is not discarded when Hebrew is unavailable')
}
const nobody=render({...archive,items:[{...post,translation_status:'media_only',text_he:null,source_excerpt:'',has_media:true}]})
assert.ok(nobody.includes('No source body text was retained')&&nobody.includes('אין תמלול')&&!nobody.includes(post.source_excerpt))
assert.ok(nobody.includes('Media is unavailable')&&nobody.includes('המדיה אינה זמינה'))
assert.ok(render({...archive,items:[{...post,translation_status:'not_retained',text_he:null}]}).includes('אינה משוחזרת'))
assert.ok(render(undefined,{error:'error'}).includes('role="alert"'))
assert.ok(render({...archive,items:[]}).includes('אין כרגע הודעות עברית'))
assert.equal(parseTruthArchive(null).status,'UNAVAILABLE')
assert.equal(parseTruthArchive({...archive,items:new Array(21).fill(post)}).status,'UNAVAILABLE')
for(const corrupt of [{truth_url:'javascript:alert(1)'},{relay_url:'https://t.me/evil/123'},
  {translation_status:'translated',text_he:'original English'}, {sent_at:'2099-01-01T00:00:00Z'},
  {original_published_at:post.sent_at}])assert.equal(parseTruthArchive({...archive,items:[{...post,...corrupt}]}).items.length,0)
const hostile=render({...archive,items:[{...post,text_he:'<script>עברית</script>',source_excerpt:'<img src=x onerror=alert(1)>'}]})
assert.ok(hostile.includes('&lt;script&gt;')&&!hostile.includes('<script>')&&!hostile.includes('<img src=x'))
const available={...post,has_media:true,media:{version:'trump_truth_media_v1',status:'available',kind:'photo',asset_token:'a'.repeat(64),mime_type:'image/jpeg',bytes:4}}
const photo=render({...archive,items:[available]})
assert.ok(photo.includes('/api/scanner/trump-media/'+'a'.repeat(64))&&photo.includes('loading="lazy"'))
const video=render({...archive,items:[{...available,media:{...available.media,kind:'video',mime_type:'video/mp4'}}]})
assert.ok(video.includes('<video')&&video.includes('preload="none"')&&!video.includes('autoplay'))
const forged=render({...archive,items:[{...available,media:{...available.media,asset_token:'https://api.telegram.org/private'}}]})
assert.ok(!forged.includes('api.telegram.org')&&forged.includes('המדיה אינה זמינה'))
const more=render({...archive,next_cursor:post.truth_post_id},{loading:true,onMore:()=>{}})
assert.ok(more.includes('disabled=""')&&more.includes('טוען'))
assert.ok(render(archive,{he:false}).includes('Original publication time: not verified'))
assert.ok(render().includes('תצוגה שמורה'))
const css=readFileSync('src/TrumpTruthNews.css','utf8')
assert.match(css,/@media \(max-width: 600px\).*grid-template-columns: minmax\(0,1fr\)/s)
assert.match(css,/white-space: pre-wrap/)
if(process.env.TRUTH_PREVIEW_HTML)writeFileSync(process.env.TRUTH_PREVIEW_HTML,`<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{background:#0c1425;color:#ecf2fa;font:16px system-ui;margin:12px}a{color:#8ac8ff}${css}</style></head><body><p>סינתטי בלבד — אין חיבור למערכת או למסחר</p>${render({...archive,items:[post,{...post,id:'trump-truth:117500000000000124',truth_post_id:'117500000000000124',truth_url:'https://truthsocial.com/@realDonaldTrump/117500000000000124',translation_status:'media_only',text_he:null,has_media:true}]})}</body></html>`)
console.log('Actual NEWS website/MiniApp route renders separate Hebrew Truth archive')
