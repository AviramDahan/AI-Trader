import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { candidate, fixtureResearch as research, fixtureDashboard as dashboard } from './system-activity-fixtures.mjs'

const result = await build({ entryPoints: ['src/SystemActivity.tsx','src/systemActivityModel.ts','src/SystemNetwork.tsx'], bundle: true, write: false,
  outdir: 'unused', platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react','react/jsx-runtime'],
  plugins: [{ name: 'isolated-render', setup(b) {
    b.onResolve({ filter: /^\.\/appShared$/ }, () => ({ path: 'stub', namespace: 'stub' }))
    b.onResolve({ filter: /\.css$/ }, () => ({ path: 'css', namespace: 'stub' }))
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: "export const API_ORIGIN='http://isolated.invalid'" }))
  } }] })
const load = name => {
  const m = { exports: {} }
  new Function('require','module','exports',result.outputFiles.find(f => f.path.endsWith(name+'.js')).text)(createRequire(import.meta.url), m, m.exports)
  return m.exports
}
const { buildActivity, activityRevision, finite } = load('systemActivityModel')
const { SystemActivityView } = load('SystemActivity')
const { buildNetwork, crawlerRoute, NETWORK_LIMIT, SystemNetwork } = load('SystemNetwork')
let assertions = 0
const check = v => { assert.ok(v); assertions++ }
const equal = (a,b) => { assert.deepEqual(a,b); assertions++ }
const items = buildActivity(research,dashboard)
equal(items.length,9)
const stock = ticker => items.find(v => v.ticker === ticker)
equal(stock('ALFA').station,'technical')
equal(stock('BETA').station,'targets') // PASS is not proof of evidence or AI
equal(stock('GAMA').station,'evidence')
equal(stock('DELT').station,'ai')
equal(stock('ECHO').state,'blocked')
equal(stock('ECHO').reason,'allocation_blocked')
equal(stock('FOXT').station,'order')
equal(stock('FOXT').state,'waiting')
equal(stock('GOLF').state,'uncertain')
equal(stock('HOTL').station,'position')
equal(stock('INDI').station,'exit')
equal(items.filter(i => i.ticker === 'HOTL').length,1) // Shadow not an independent main entry
equal(new Set(items.map(i => i.id)).size,items.length)
equal(buildActivity(null,null),[])
equal(buildActivity(research,{signals:[],trades:[{id:100,ticker:'OLD',status:'closed',closed_at:'2026-10-01T15:00:00Z'}]}).filter(i => i.ticker==='OLD').length,0)
equal(buildActivity(research,{signals:[],trades:[{id:100,ticker:'OLD',status:'open',opened_at:'2026-10-01T15:00:00Z'}]}).filter(i => i.ticker==='OLD').length,1)
equal(buildActivity(research,null).filter(i => i.kind === 'signal').length,5) // research link not lost if dashboard is capped
const unlinked = buildActivity(null,{ signals: [{id:9,ticker:'TEST',actual_entry:100,status:'ENTERED'}] })[0]
equal(unlinked.state,'uncertain'); check(unlinked.station !== 'position')
const expired = buildActivity(null,{ signals: [{id:9,ticker:'TEST',status:'EXPIRED'}] })[0]
equal(expired.station,'signal'); equal(expired.reason,'EXPIRED')
const older = candidate('ALFA',{scan_id:'older',at:'2026-10-08T15:00:00Z',rejection:'pre_no_fresh_quote'})
equal(buildActivity({...research,records:[older,...research.records]},dashboard).filter(i => i.ticker === 'ALFA').length,1)
equal(buildActivity({...research,records:[older,...research.records]},dashboard).find(i => i.ticker === 'ALFA').reason,null)
equal(buildActivity({records:[candidate('WAIT',{rejection:'pre_waiting_regular_session',rejection_stage:'session_wait'})]},null)[0].state,'waiting')
equal(finite(null),null); equal(finite(''),null); equal(finite(false),null); equal(finite(Infinity),null); equal(finite(0),0)
equal(activityRevision(stock('HOTL')),activityRevision(buildActivity({...research,generated_at:'2030-01-01T00:00:00Z'},dashboard).find(i => i.ticker==='HOTL')))
check(activityRevision(stock('GOLF')) !== activityRevision({...stock('GOLF'),state:'waiting'}))
const render = props => renderToStaticMarkup(createElement(SystemActivityView,{he:true,research,dashboard,...props}))
const html = render({selected:'trade:40'})
check(html.includes('המערכת בפעולה') && html.includes('מפת תחנות אינטראקטיבית'))
check(html.includes('role="button"') && html.includes('tabindex="0"'))
check(html.includes('dir="rtl"') && html.includes('<bdi>HOTL</bdi>'))
check(html.includes('יתרה מהפוזיציה') && html.includes('100.00%'))
check(html.includes('ממומש נטו') && html.includes('חלק פתוח ברוטו'))
check(html.includes('אינן תשואת תיק') && html.includes('Shadow אינו תיק עצמאי'))
check(!html.includes('$') && !html.includes('NaN') && !html.includes('Infinity'))
check(html.includes('106.00') && !html.includes('TP2: 106.00'))
check(html.includes('המדגם מוגבל'))
check(render({selected:'signal:1'}).includes('סיגנל כשיר; הקצאת הדמה חסומה'))
check(render({selected:'signal:3'}).includes('אי־ודאות בהתאוששות'))
check(render({selected:'scan:synthetic-ALFA:ALFA'}).includes('אין סיגנל מקושר במדגם'))
const singleV1 = {...dashboard,signals:[{id:8,ticker:'VONE',planned_entry:100,current_stop:97,rr1:1,rr2:2,rr3:3,tp1:103,tp2:106,tp3:109,operational_tp1_pct:0,operational_tp2_pct:1,operational_tp3_pct:0,status:'ACTIVE'}],trades:[]}
const v1 = render({dashboard:singleV1,research:{records:[]},selected:'signal:8'})
check(v1.includes('2.00R') && !v1.includes('1.00R'))
check(v1.includes('106.00'))
const escape = render({dashboard:{...dashboard,signals:dashboard.signals.map(s => ({...s,company:'<img src=x onerror=alert(1)>'}))}})
check(escape.includes('&lt;img') && !escape.includes('<img src=x'))
check(render({error:'HTTP 503'}).includes('role="alert"'))
check(render({research:null,dashboard:null}).includes('ממתין לנתונים'))
check(render({dashboard:{...dashboard,market:{is_open:false}}}).includes('מחוץ למסחר'))
check(render({he:false}).includes('System in motion'))
check(render({onlyFollowed:true,followed:['HOTL']}).includes('HOTL'))
check(!render({onlyFollowed:true,followed:['HOTL']}).includes('<bdi>ALFA</bdi>'))
check(render({station:'order'}).includes('<bdi>FOXT</bdi>'))
check(!render({station:'order'}).includes('<bdi>DELT</bdi>'))
check(render({selected:'disappeared'}).includes('אין בכך הוכחה שהפוזיציה נסגרה'))
const legacy = {...dashboard,trades:[{...dashboard.trades[0],legacy_position_id:7}]}
check(render({dashboard:legacy,selected:'trade:40',research:{...research,outcomes:[{trade_id:40,cohort:'Legacy',realized_net_pct:null,realized_net_r:null}]}}).includes('חסרה היסטוריה מלאה'))
const css = readFileSync('src/systemActivity.css','utf8')
check(css.includes('prefers-reduced-motion:reduce'))
// Continuous motion belongs only to the explicitly decorative crawler, not event evidence.
check(css.includes('.visual-motion-enabled .system-crawler') && css.includes('system-visual-tour'))
check(css.includes('.visual-motion-enabled .system-crawler-leg { animation: none; }'))
const graph = buildNetwork(items)
equal(graph.flatMap(c => c.nodes).length, items.length)
equal(graph.flatMap(c => c.nodes.map(n => n.item.id)).sort(), items.map(i => i.id).sort())
equal(buildNetwork([...items].reverse()), graph)
equal(crawlerRoute([...items].reverse()), crawlerRoute(items))
const dense = Array.from({length: 100}, (_, n) => ({...stock('HOTL'), id:`synthetic:${n}`}))
const denseCluster = buildNetwork(dense).find(c => c.station === 'position')
equal(denseCluster.nodes.length, NETWORK_LIMIT)
equal(denseCluster.omitted, 100-NETWORK_LIMIT)
check(denseCluster.nodes.every(n => Number.isFinite(n.x) && Number.isFinite(n.y)))
equal(buildNetwork([]).flatMap(c => c.nodes), [])
equal(crawlerRoute([]),'M 610 340 L 610 340')
const network = props => renderToStaticMarkup(createElement(SystemNetwork,{he:true,items,changed:new Set(),station:'all',setStation:()=>{},selected:null,select:()=>{},available:true,marketOpen:true,...props}))
check(network({}).includes('visual-motion-enabled'))
check(!network({available:false}).includes('visual-motion-enabled'))
check(!network({items:[]}).includes('visual-motion-enabled'))
check(network({}).includes('אנימציה חזותית בלבד — לא מצב Worker'))
check(network({}).includes('נקודות הרקע דקורטיביות'))
check(network({}).includes('מסלול מניה: HOTL'))
check(network({changed:new Set(['trade:40'])}).includes('system-arrival'))
check(!network({available:false,changed:new Set(['trade:40'])}).includes('system-arrival'))
const networkSource = readFileSync('src/SystemNetwork.tsx','utf8')
check(!networkSource.includes('fetch(') && !networkSource.includes('Math.random'))
check(networkSource.includes("visibilityState !== 'hidden'"))
const component = readFileSync('src/SystemActivity.tsx','utf8')
check(!/method:\s*['"](?:POST|PUT|DELETE)/.test(component))
check(component.includes('controller.abort()') && component.includes('inFlight') && component.includes("visibilityState === 'hidden'"))
console.log(`System activity model + RTL rendering: ${assertions} assertions passed`)
