import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {createRequire} from 'node:module'
import {createElement} from 'react'
import {renderToStaticMarkup} from 'react-dom/server'
import {readFileSync} from 'node:fs'
import {teamFixture} from './admin-system-fixtures.mjs'
const bundle=await build({entryPoints:['src/AdminAgentOffice.tsx','src/adminAgentOfficeModel.ts'],outdir:'unused',bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime'],plugins:[{name:'css',setup(b){b.onResolve({filter:/\.css$/},()=>({path:'css',namespace:'stub'}));b.onLoad({filter:/.*/,namespace:'stub'},()=>({contents:''}))}}]})
const load=name=>{const m={exports:{}};new Function('require','module','exports',bundle.outputFiles.find(f=>f.path.endsWith(name+'.js')).text)(createRequire(import.meta.url),m,m.exports);return m.exports}
const {AdminAgentOffice}=load('AdminAgentOffice'),model=load('adminAgentOfficeModel')
const now=Date.now(),render=(report,fresh=true)=>renderToStaticMarkup(createElement(AdminAgentOffice,{report,fresh,now}))
const normal=render(teamFixture())
assert.equal((normal.match(/class="agent-desk /g)||[]).length,8)
for(const role of model.AGENT_ROLES)assert.ok(normal.includes(role.title),role.title)
assert.ok(normal.includes('הסבב האחרון הסתיים'))
assert.ok(normal.includes('אינו עובד ברציפות'))
assert.ok(normal.includes('זה לא אומר שאין ממצאים פתוחים'))
assert.ok(normal.includes('aria-controls="agent-office-detail"'))
assert.ok(normal.includes('חזרה לעמדות הצוות'))
assert.equal((normal.match(/aria-pressed="true"/g)||[]).length,1)
assert.ok(normal.includes('rel="noopener noreferrer"'))
const running=model.teamMembers(teamFixture('team-running'),Date.now(),true)
assert.equal(running.filter(a=>a.state==='running').length,4)
assert.ok(render(teamFixture('team-running')).includes('סוכנים דווחו כפעילים'))
assert.ok(render(teamFixture('team-blocked')).includes('דווח חסם'))
assert.ok(render(teamFixture('team-blocked')).includes('ממתין לאישור מפורש'))
const noBlocker=teamFixture('team-blocked');delete noBlocker.agents[3].blocker_code;assert.ok(render(noBlocker).includes('הדיווח לא כלל סיבה מאומתת לחסם'))
assert.ok(model.teamMembers(teamFixture('team-stale'),Date.now(),true).every(a=>a.state==='stale'))
assert.ok(render(teamFixture(),false).includes('מציג דיווח שמור, לא פעילות חיה'))
assert.equal(render(teamFixture(),false).includes('href='),false)
assert.ok(model.teamMembers(null,now,true).every(a=>a.state==='unknown'))
assert.ok(render(null).includes('טרם התקבל דיווח צוות מאומת'))
for(const report of [ {...teamFixture(),version:2}, {...teamFixture(),source:'untrusted'}, {...teamFixture(),reported_at:new Date(now+60000).toISOString()} ])assert.ok(model.teamMembers(report,now,true).every(a=>a.state==='unknown'))
const malformed=teamFixture();malformed.agents.push(malformed.agents[0]);assert.ok(model.teamMembers(malformed,now,true).every(a=>a.state==='unknown'))
const duplicate=teamFixture();duplicate.agents=duplicate.agents.slice(0,2);duplicate.agents.push(duplicate.agents[0]);assert.equal(model.teamMembers(duplicate,now,true)[0].state,'unknown')
const missing=teamFixture();missing.agents=missing.agents.filter(a=>a.id!=='ai');assert.equal(model.teamMembers(missing,now,true).find(a=>a.id==='ai').state,'unknown')
const future=teamFixture();future.agents[0].observed_at=new Date(now+10000).toISOString();assert.equal(model.teamMembers(future,now,true)[0].state,'unknown')
const hostile=teamFixture();hostile.agents[0].task='<script>alert(1)</script>';assert.equal(render(hostile).includes('<script>'),false)
for(const url of ['javascript:alert(1)','https://github.com/other/repo/pull/1','https://github.com/AviramDahan/AI-Trader/pull/74?private=token'])assert.equal(model.safeTeamLink(url),null)
assert.equal(model.safeTeamLink(teamFixture().report_url),teamFixture().report_url)
const source=readFileSync('src/AdminAgentOffice.tsx','utf8')+readFileSync('src/adminAgentOfficeModel.ts','utf8')
for(const forbidden of ['fetch(','localStorage','sessionStorage','sendData','/completion','dangerouslySetInnerHTML'])assert.equal(source.includes(forbidden),false)
const css=readFileSync('src/adminAgentOffice.css','utf8');assert.ok(css.includes('prefers-reduced-motion'));assert.ok(css.includes('min-height:52px'))
console.log('Agent office: 8 real roles, historical/fresh/stale/missing reports, safe links, read-only rendering and accessibility PASS (synthetic)')
