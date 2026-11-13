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
assert.ok(normal.includes('role="tablist"'))
assert.ok(normal.includes('צוות Agents'))
assert.ok(normal.includes('id="ops-team-panel"'))
assert.ok(normal.includes('aria-controls="ops-systems-panel"'))
assert.ok(normal.includes('פקודות דמה ממתינות לביצוע'))
assert.ok(!normal.includes('פקודות ממתינות לכניסה'))
const pendingFixture=opsFixture()
pendingFixture.nodes.find(n=>n.id==='paper').metrics={open_positions:2,pending_orders:4,holds:2}
const pendingMarkup=render(pendingFixture)
assert.ok(pendingMarkup.includes('פקודות דמה ממתינות לביצוע</dt><dd><bdi>4</bdi>'))
assert.ok(!pendingMarkup.includes('פקודות דמה ממתינות או חסומות לבירור'))
assert.ok(pendingMarkup.includes('פקודות באי־ודאות</dt><dd><bdi>2</bdi>'))
for(const text of ['מקורות חדשות','דיווחי SEC','Ollama במחשב','OpenRouter','ניטור פוזיציות','גיבוי מוצפן','API','PostgreSQL','המערכת פועלת; יש פערים לבדיקה','פקודה ממתינה אינה פוזיציה','יחידה']) assert.ok(normal.includes(text),text)
assert.equal((normal.match(/class="ops-stage"/g)||[]).length,5)
assert.equal((normal.match(/class="ops-card /g)||[]).length,13)
assert.ok(render(opsFixture('failure')).includes('יש רכיב שדורש טיפול'))
const scheduledWait=opsFixture()
scheduledWait.nodes.find(n=>n.id==='news_feed').state='idle'
scheduledWait.nodes.find(n=>n.id==='news_feed').reason='scheduled_wait'
assert.ok(render(scheduledWait).includes('ממתין למחזור האיסוף המתוזמן הבא; אין כאן ניסיון התאוששות'))
assert.notEqual(model.OPS_REASONS.scheduled_wait,model.OPS_REASONS.retry_backoff)
const retryWait=opsFixture()
retryWait.nodes.find(n=>n.id==='news_feed').reason='retry_backoff'
assert.ok(render(retryWait).includes('ממתין לניסיון חוזר לפי מדיניות ההתאוששות'))
assert.ok(render(opsFixture('busy')).includes('המודל עסוק או נטען'))
assert.ok(render(opsFixture('stale')).includes('מציג מידע שמור'))
assert.ok(render(opsFixture('closed')).includes('שוק סגור'))
const empty=render(null)
assert.ok(empty.includes('ממתין לתמונת מצב מורשית'))
assert.equal(empty.includes('>0<'),false)
assert.equal(empty.includes('פעילות תקינה לפי'),false)
assert.ok(render(opsFixture(),'Synthetic timeout').includes('העדכון האחרון אינו מאומת'))
// Audited live ambiguities: complete work != full coverage, null != missing lease.
assert.ok(render(opsFixture('partial')).includes('הושלמו 460 מתוך 515'))
assert.ok(render(opsFixture('partial')).includes('נותרו 55 להשלמה'))
assert.ok(normal.includes('שלב הגילוי הושלם'))
const onlyBackup={...opsFixture(),nodes:opsFixture().nodes.filter(n=>n.id==='backup')}
assert.equal(render(onlyBackup).includes('בעלות עובד לתפקיד'),false)
const onlyMonitor={...opsFixture(),nodes:opsFixture().nodes.filter(n=>n.id==='monitor').map(n=>({...n,lease_holders:null}))}
assert.ok(render(onlyMonitor).includes('בעלות עובד לתפקיד'))
assert.ok(render(onlyMonitor).includes('לא אומתה'))
assert.ok(render(opsFixture('stale')).includes('מצב השוק לא אומת כעת'))
assert.ok(render(opsFixture(),'Synthetic timeout').includes('מצב השוק לא אומת כעת'))
const partialHealthy={...opsFixture('partial'),overall:'observed_operational'}
assert.ok(render(partialHealthy).includes('המערכת פועלת; גילוי הדיווחים בהשלמה'))
const missingCoverage=opsFixture();missingCoverage.nodes.find(n=>n.id==='sec_intelligence').metrics={}
assert.ok(render(missingCoverage).includes('מצב השלמת הגילוי לא אומת'))
assert.equal(render(missingCoverage).includes('הושלמו 0 מתוך'),false)
const secNode=opsFixture().nodes.find(n=>n.id==='sec_intelligence')
for(const metrics of [{issuers:0,completed:0},{issuers:515,completed:null},{issuers:515,completed:516},
  {issuers:515,completed:-1},{issuers:515,completed:NaN},{issuers:'515',completed:460},
  {issuers:515.1,completed:460},{issuers:Infinity,completed:460}])assert.equal(model.secDiscoveryCoverage({...secNode,metrics}),null)
assert.deepEqual(model.secDiscoveryCoverage({...secNode,metrics:{issuers:515,completed:0}}),{completed:0,total:515,remaining:515})
assert.deepEqual(model.secDiscoveryCoverage({...secNode,metrics:{issuers:515,completed:515}}),{completed:515,total:515,remaining:0})
const stalePartial={...opsFixture('partial'),observed_at:new Date(Date.now()-120000).toISOString()}
assert.ok(render(stalePartial).includes('השלמת הגילוי לפי הנתונים השמורים'))
assert.ok(render({...partialHealthy,overall:'failed'}).includes('יש רכיב שדורש טיפול'))
assert.ok(model.marketDescription(opsFixture('closed'),false).includes('מצב השוק לא אומת כעת'))
assert.ok(model.marketDescription(opsFixture('closed'),true).includes('מחוץ למסחר הרגיל'))
assert.equal(model.marketDescription(null,false),'מצב השוק לא אומת')
const hostile=opsFixture();hostile.nodes[0].metrics.queue='<script>alert(1)</script>'
assert.equal(render(hostile).includes('<script>'),false)
assert.ok(render(hostile).includes('&lt;script&gt;'))
hostile.nodes[0].reason_codes=['invalid_json','untrusted_unknown_code']
assert.ok(render(hostile).includes('תשובת AI אינה JSON תקין'))
assert.equal(render(hostile).includes('untrusted_unknown_code'),false)
hostile.nodes[0].providers=[{id:'globenewswire',status:'requires_configuration',last_success_at:new Date().toISOString(),last_attempt_at:new Date().toISOString(),http_status:403,error_code:'http_error'}]
assert.ok(render(hostile).includes('המקור דחה את הגישה (403); לא אומתה התאוששות'))
assert.ok(render(hostile).includes('הצלחה אחרונה'))
hostile.nodes[0].providers[0].error_code='SECRET_UNTRUSTED'
hostile.nodes[0].providers[0].http_status=null
assert.equal(render(hostile).includes('SECRET_UNTRUSTED'),false)
const source=readFileSync('src/AdminSystemMiniApp.tsx','utf8')+readFileSync('src/adminSystemModel.ts','utf8')
// Throughput is not established by healthy collectors, a zero queue, or an
// unrelated notice. The backend supplies a bounded current-version cohort.
const funnelReview=opsFixture(),funnelNode=funnelReview.nodes.find(n=>n.id==='news_feed')
funnelNode.state='degraded';funnelNode.reason='news_funnel_review_required'
funnelNode.metrics={queue:0,news_events_6h:100,news_identity_blocked_6h:90,
  news_analysis_done_6h:5,news_routed_6h:0,news_cohort_sent_6h:0,news_window_sent_6h:1,news_funnel_review_required:true}
const funnelMarkup=render(funnelReview)
assert.ok(funnelMarkup.includes('נדרש לבדוק את המעבר מאיסוף לפרסום'))
assert.ok(funnelMarkup.includes('אירועים חדשים בחלון (עד 6 שעות)</dt><dd><bdi>100</bdi>'))
assert.ok(funnelMarkup.includes('אירועים שנשלחו מהקבוצה</dt><dd><bdi>0</bdi>'))
assert.ok(funnelMarkup.includes('כולל אירועים ישנים'))
assert.ok(funnelMarkup.includes('תור ריק אינו אישור איכות או כיסוי'))
const noFunnel=opsFixture(),unknownFunnelNode=noFunnel.nodes.find(n=>n.id==='news_feed')
unknownFunnelNode.state='unknown';unknownFunnelNode.reason='news_funnel_unverified'
unknownFunnelNode.metrics={news_events_6h:null,news_funnel_review_required:null}
assert.ok(render(noFunnel).includes('אין תצפית משפך עדכנית ותקפה'))
assert.ok(render(noFunnel).includes('אירועים חדשים בחלון (עד 6 שעות)</dt><dd><bdi>לא זמין</bdi>'))
for(const forbidden of ['localStorage','sessionStorage','initDataUnsafe','sendData','/completion','method:'])assert.equal(source.includes(forbidden),false)
const poller=readFileSync('src/readPoller.ts','utf8');assert.ok(poller.includes('options.headers()'))
const app=readFileSync('src/App.tsx','utf8');assert.ok(app.includes('isAdminSystemEntry(location.search, location.hash)'))
assert.ok(app.includes('isMiniAppEntry(location.search) ? null : token'))
console.log('Private Admin system map: auth hints, missing/stale/error/busy/closed data, escaping and 13 read-only nodes PASS (synthetic only)')
