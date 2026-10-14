/** GET-only local visual QA. Synthetic data, no live API/Telegram/AI. */
import { createServer } from 'node:http'
import { build } from 'esbuild'
const output=await build({stdin:{resolveDir:process.cwd(),sourcefile:'admin-preview.tsx',loader:'tsx',contents:`
  import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
  import {AdminSystemPanel} from './src/AdminSystemMiniApp';import {opsFixture} from './tests/admin-system-fixtures.mjs';
  import './src/adminSystemMiniApp.css';
  function Preview(){const [mode,setMode]=useState(new URLSearchParams(location.search).get('state')||'normal'),[tick,setTick]=useState(0);
    const data=React.useMemo(()=>opsFixture(mode),[mode,tick]);return <><div style={{padding:12,background:'#282132',color:'#fff',font:'12px Arial',textAlign:'center'}}>תצוגת בדיקה בלבד · נתונים סינתטיים · לא Production
    <div style={{display:'flex',gap:6,justifyContent:'center',flexWrap:'wrap',marginTop:8}}>{['normal','partial','failure','busy','stale','closed','empty','team-running','team-stale','team-blocked','team-missing'].map(v=><button onClick={()=>setMode(v)} key={v}>{v}</button>)}</div></div>
    <AdminSystemPanel data={data} onRefresh={()=>setTick(t=>t+1)}/></>}
  createRoot(document.getElementById('root')).render(<Preview/>);`},bundle:true,write:false,outdir:'unused',platform:'browser',jsx:'automatic',
  plugins:[{name:'no-live-api',setup(b){b.onResolve({filter:/^\.\/appShared$/},()=>({path:'shared',namespace:'stub'}));b.onLoad({filter:/.*/,namespace:'stub'},()=>({contents:"export const API_ORIGIN='http://isolated.invalid'"}))}}]})
const js=output.outputFiles.find(f=>f.path.endsWith('.js')).text,css=output.outputFiles.find(f=>f.path.endsWith('.css')).text
createServer((req,res)=>{if(req.method!=='GET'){res.writeHead(405);res.end();return}
  const path=new URL(req.url,'http://127.0.0.1:4326').pathname
  if(path==='/preview.js'){res.setHeader('Content-Type','application/javascript');res.end(js);return}
  if(path==='/preview.css'){res.setHeader('Content-Type','text/css');res.end(css);return}
  if(path!=='/'){res.writeHead(404);res.end();return}
  res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<!doctype html><html lang="he" dir="rtl"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Admin system map · Synthetic preview</title><link rel="stylesheet" href="/preview.css"></head><body style="margin:0;background:#0a1019"><main id="root"></main><script src="/preview.js"></script></body></html>')
}).listen(4326,'127.0.0.1',()=>process.stdout.write('Synthetic Admin preview: http://127.0.0.1:4326\n'))
