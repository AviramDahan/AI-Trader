// Actual public parser/card SSR; synthetic retained records, no HTTP or model.
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import * as React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

globalThis.fetch=()=>{throw new Error('No HTTP in source-channel presentation tests')}
const built=await build({entryPoints:['src/TrumpTruthNews.tsx'],bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime'],plugins:[{name:'isolated-channel',setup(b){
  b.onResolve({filter:/^\.\/appShared$/},()=>({path:'shared',namespace:'stub'}))
  b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}))
  b.onLoad({filter:/.*/,namespace:'stub'},a=>({contents:a.path==='shared'?"export const API_ORIGIN='https://isolated.invalid'":''}))
}}]})
const module={exports:{}};new Function('require','module','exports',built.outputFiles[0].text)(createRequire(import.meta.url),module,module.exports)
const {parseTruthArchive,TrumpTruthNewsView}=module.exports
const id='tg:1462338131:42',url='https://t.me/real_DonaldJTrump/42'
const post={id:'trump-truth:'+id,truth_post_id:id,truth_url:url,relay_url:url,
  source_kind:'trump_telegram_channel_v1',source_verification:'channel_only',publication_policy:'telegram_channel_original_v1',
  source_excerpt:'An actual retained source statement.',translation_status:'translated',text_he:'אמירה שנשמרה מהערוץ.',
  relay_published_at:'2026-10-25T15:00:00Z',observed_at:'2026-10-25T15:01:00Z',sent_at:'2026-10-25T15:02:00Z',original_published_at:null,
  is_repost:false,has_media:false,delivery_status:'sent',media:{status:'unavailable',kind:null}}
const legacy={...post,id:'trump-truth:117500000000000123',truth_post_id:'117500000000000123',truth_url:'https://truthsocial.com/@realDonaldTrump/117500000000000123',
  relay_url:'https://t.me/realdonaldtrump_truth/123',source_kind:'trump_truth_relay_v1',source_verification:'relay_only',publication_policy:'original_relay_v1',text_he:'תרגום ישן שנשמר.'}
const page=items=>({version:1,status:'READY',generated_at:'2026-10-25T15:03:00Z',items,next_cursor:null})
const parsed=parseTruthArchive(page([post,legacy]))
assert.equal(parsed.items.length,2,'new pinned Telegram publication and retained Truth history must coexist')
for(const he of [true,false]){
  const html=renderToStaticMarkup(React.createElement(TrumpTruthNewsView,{he,data:parseTruthArchive(page([post]))}))
  assert.ok(html.includes(post.text_he)&&html.includes('Telegram')&&html.includes(url))
  assert.ok(!html.includes('Truth Social'),'Telegram source must not be described as a Truth Social post')
  assert.ok(!html.includes('truthsocial.com')&&!html.includes('realdonaldtrump_truth'))
  assert.ok(html.includes('lang="he" dir="rtl"'))
  assert.ok(!html.replace(/<details[^>]*>[\s\S]*?<\/details>/g,'').includes(post.source_excerpt),'new source English is not displayed automatically')
}
for(const change of [{truth_url:'https://t.me/other/42'},{relay_url:'https://t.me/real_DonaldJTrump/43'},
  {truth_post_id:'tg:1462338132:42'},{truth_post_id:'tg:1462338131:042'},{source_verification:'relay_only'},
  {publication_policy:'original_relay_v1'},{translation_status:'unavailable',text_he:null},{translation_status:'not_retained',text_he:null},
  {translation_status:'media_only',text_he:null},{text_he:'א This otherwise untranslated English text must not pretend to be Hebrew.'}])assert.equal(parseTruthArchive(page([{...post,...change}])).items.length,0)
const tooLarge={...post,id:'trump-truth:tg:1462338131:2147483648',truth_post_id:'tg:1462338131:2147483648',truth_url:'https://t.me/real_DonaldJTrump/2147483648',relay_url:'https://t.me/real_DonaldJTrump/2147483648'}
assert.equal(parseTruthArchive(page([tooLarge])).items.length,0)
assert.equal(parseTruthArchive({...page([]),next_cursor:tooLarge.truth_post_id}).status,'UNAVAILABLE')
const emptyMedia={...post,source_excerpt:'',translation_status:'media_only',text_he:null,has_media:true}
assert.equal(parseTruthArchive(page([emptyMedia])).items.length,1)
const oldHtml=renderToStaticMarkup(React.createElement(TrumpTruthNewsView,{he:true,data:parseTruthArchive(page([legacy]))}))
assert.ok(oldHtml.includes('Truth Social')&&oldHtml.includes(legacy.source_excerpt)&&oldHtml.includes(legacy.text_he))
assert.equal(parseTruthArchive({...page([post]),next_cursor:id}).next_cursor,id)
assert.equal(parseTruthArchive({...page([post]),next_cursor:'tg:1462338132:42'}).status,'UNAVAILABLE')
const hostile=renderToStaticMarkup(React.createElement(TrumpTruthNewsView,{he:true,data:parseTruthArchive(page([{...post,text_he:'<script>בדיקת עברית בטוחה ארוכה מאוד</script>'}]))}))
assert.ok(hostile.includes('&lt;script&gt;')&&!hostile.includes('<script>'))
console.log('Pinned Telegram Hebrew cards, exact source links/cursors and old Truth history passed')
