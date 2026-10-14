import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { opsFixture } from './admin-system-fixtures.mjs'
const bundle=await build({entryPoints:['src/AdminSystemMiniApp.tsx','src/adminSystemModel.ts'],outdir:'unused',bundle:true,write:false,
  platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime'],
  plugins:[{name:'isolated',setup(b){b.onResolve({filter:/^\.\/appShared$/},()=>({path:'shared',namespace:'stub'}));b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}));b.onLoad({filter:/.*/,namespace:'stub'},a=>({contents:a.path==='css'?'':"export const API_ORIGIN='http://isolated.invalid'"}))}}]})
const load=name=>{const m={exports:{}};new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith(name+'.js')).text)(createRequire(import.meta.url),m,m.exports);return m.exports}
const {AdminSystemPanel}=load('AdminSystemMiniApp'),model=load('adminSystemModel')
const render=(data,error='')=>renderToStaticMarkup(createElement(AdminSystemPanel,{data,error}))
assert.equal(model.isAdminSystemEntry('?miniapp=1','#tgWebAppStartParam=operations'),true)
assert.equal(model.isAdminSystemEntry('?tgWebAppStartParam=operations',''),true)
assert.equal(model.isAdminSystemEntry('?miniapp=1','#tgWebAppStartParam=live'),false)
assert.equal(model.telegramAdminData({Telegram:{WebApp:{initData:'fixture-signed'}}}),'fixture-signed')
assert.equal(model.telegramAdminData({location:{hash:'#tgWebAppData=UNVERIFIED'}}),'')
assert.equal(model.telegramAdminData({Telegram:{WebApp:{initData:'x'.repeat(8193)}}}),'')
assert.equal(model.snapshotFresh(opsFixture(),Date.now()),true)
assert.equal(model.snapshotFresh(opsFixture('stale'),Date.now()),false)
assert.equal(model.snapshotFresh({...opsFixture(),observed_at:new Date(Date.now()+60000).toISOString()},Date.now()),false)
const normal=render(opsFixture())
for(const text of ['מקורות חדשות','דיווחי SEC','Ollama במחשב','OpenRouter','ניטור פוזיציות','גיבוי מוצפן','API','PostgreSQL','המערכת פועלת; יש פערים לבדיקה','פקודה ממתינה אינה פוזיציה','יחידה']) assert.ok(normal.includes(text),text)
assert.equal((normal.match(/class="ops-stage"/g)||[]).length,5)
assert.equal((normal.match(/class="ops-card /g)||[]).length,13)
assert.ok(render(opsFixture('failure')).includes('יש רכיב שדורש טיפול'))
assert.ok(render(opsFixture('busy')).includes('המודל עסוק או נטען'))
assert.ok(render(opsFixture('stale')).includes('מציג מידע שמור'))
assert.ok(render(opsFixture('closed')).includes('שוק סגור'))
const empty=render(null)
assert.ok(empty.includes('ממתין לתמונת מצב מורשית'))
assert.equal(empty.includes('>0<'),false)
assert.equal(empty.includes('פעילות תקינה לפי'),false)
assert.ok(render(opsFixture(),'Synthetic timeout').includes('העדכון האחרון אינו מאומת'))
const hostile=opsFixture();hostile.nodes[0].metrics.queue='<script>alert(1)</script>'
assert.equal(render(hostile).includes('<script>'),false)
assert.ok(render(hostile).includes('&lt;script&gt;'))
hostile.nodes[0].reason_codes=['invalid_json','untrusted_unknown_code']
assert.ok(render(hostile).includes('תשובת AI אינה JSON תקין'))
assert.equal(render(hostile).includes('untrusted_unknown_code'),false)
const source=readFileSync('src/AdminSystemMiniApp.tsx','utf8')+readFileSync('src/adminSystemModel.ts','utf8')
for(const forbidden of ['localStorage','sessionStorage','initDataUnsafe','sendData','/completion','method:'])assert.equal(source.includes(forbidden),false)
const poller=readFileSync('src/readPoller.ts','utf8');assert.ok(poller.includes('options.headers()'))
const app=readFileSync('src/App.tsx','utf8');assert.ok(app.includes('isAdminSystemEntry(location.search, location.hash)'))
assert.ok(app.includes('isMiniAppEntry(location.search) ? null : token'))
console.log('Private Admin system map: auth hints, missing/stale/error/busy/closed data, escaping and 13 read-only nodes PASS (synthetic only)')
