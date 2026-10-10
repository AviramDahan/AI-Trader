import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { build } from 'esbuild'
const result = await build({entryPoints:['src/telegramMiniApp.ts'],bundle:true,write:false,platform:'node',format:'cjs'})
const module = {exports:{}}
new Function('module','exports',result.outputFiles[0].text)(module,module.exports)
const {mountTelegramMiniApp,isMiniAppEntry,preserveMiniApp,TELEGRAM_SDK} = module.exports
let assertions = 0
const equal = (a,b) => {assert.deepEqual(a,b);assertions++}
function fixture(search='?tab=live&miniapp=1',hash='#tgWebAppPlatform=android&tgWebAppVersion=8.0',sdk=true) {
  const styles = new Map(),classes = new Set(),scripts = [],events = new Map(),calls = []
  const app = {ready(){calls.push('ready')},expand(){calls.push('expand')},viewportStableHeight:740,
    safeAreaInset:{top:24,bottom:16},contentSafeAreaInset:{top:42},
    onEvent(name,fn){events.set(name,fn)},offEvent(name,fn){if(events.get(name)===fn)events.delete(name)}}
  const doc = {documentElement:{style:{setProperty:(k,v)=>styles.set(k,v),removeProperty:k=>styles.delete(k)},classList:{add:k=>classes.add(k),remove:k=>classes.delete(k)}},
    head:{appendChild:s=>scripts.push(s)},createElement:()=>({remove(){this.removed=true}})}
  const win = {location:{search,hash},...(sdk?{Telegram:{WebApp:app}}:{})}
  return {win,doc,app,styles,classes,scripts,events,calls}
}
equal(isMiniAppEntry('?tab=live&miniapp=1'),true)
equal(preserveMiniApp('/market?tab=signals','?miniapp=1','#tgWebAppPlatform=android'),'/market?tab=signals&miniapp=1#tgWebAppPlatform=android')
equal(preserveMiniApp('/market?tab=live','?tab=signals',''),'/market?tab=live')
equal(preserveMiniApp('/market','?miniapp=1',''),'/market?miniapp=1')
for(const search of ['', '?miniapp=0','?miniapp=true'])equal(isMiniAppEntry(search),false)
for(const [search,hash] of [['?tab=live','#tgWebAppPlatform=android&tgWebAppVersion=8'],['?miniapp=1',''],['?miniapp=1','#tgWebAppPlatform=unknown']]) {
  const f=fixture(search,hash,false);mountTelegramMiniApp(f.win,f.doc)();equal(f.scripts.length,0);equal(f.classes.size,0)
}
const f=fixture();const clean=mountTelegramMiniApp(f.win,f.doc)
equal(f.calls,['ready','expand']);equal(f.classes.has('telegram-miniapp'),true)
equal(f.styles.get('--miniapp-safe-top'),'66px');equal(f.styles.get('--miniapp-safe-bottom'),'16px')
equal(f.styles.get('--miniapp-height'),'740px');equal(f.events.size,3)
f.app.safeAreaInset={top:Infinity,left:-10};f.app.contentSafeAreaInset={top:999};f.app.viewportStableHeight=NaN
f.events.get('safeAreaChanged')();equal(f.styles.get('--miniapp-safe-top'),'200px');equal(f.styles.get('--miniapp-safe-left'),'0px')
clean();equal(f.events.size,0);equal(f.classes.size,0);equal(f.styles.size,0)
const delayed=fixture(undefined,undefined,false);const delayedClean=mountTelegramMiniApp(delayed.win,delayed.doc)
equal(delayed.scripts.length,1);equal(delayed.scripts[0].src,TELEGRAM_SDK);equal(delayed.scripts[0].async,true)
delayed.win.Telegram={WebApp:delayed.app};delayed.scripts[0].onload();delayed.scripts[0].onload()
equal(delayed.calls,['ready','expand']);delayedClean();equal(delayed.scripts[0].removed,true)
const late=fixture(undefined,undefined,false);const lateClean=mountTelegramMiniApp(late.win,late.doc);const callback=late.scripts[0].onload
lateClean();late.win.Telegram={WebApp:late.app};callback();equal(late.calls,[])
const unsupported=fixture();unsupported.app.onEvent=()=>{throw Error('old client')};unsupported.app.ready=()=>{throw Error('SDK not available')}
const unsupportedClean=mountTelegramMiniApp(unsupported.win,unsupported.doc);equal(unsupported.classes.has('telegram-miniapp'),true);unsupportedClean()
const source=readFileSync('src/telegramMiniApp.ts','utf8');
for(const forbidden of ['initDataUnsafe','sendData','requestWriteAccess','requestContact','fetch(','localStorage','sessionStorage'])equal(source.includes(forbidden),false)
const appSource=readFileSync('src/App.tsx','utf8');equal(appSource.includes("isMiniAppEntry(window.location.search) ? null : localStorage.getItem('claw_token')"),true)
const dashboardSource=readFileSync('src/ScannerDashboard.tsx','utf8');equal(dashboardSource.includes("(isMiniAppEntry(location.search) ? 'live' : 'signals')"),true)
const css=readFileSync('src/telegramMiniApp.css','utf8');equal(css.includes('overflow: hidden'),false)
console.log(`Telegram display-only Mini App: ${assertions} assertions passed (SDK mocked; no Telegram calls)`)
