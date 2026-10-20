import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'
// Isolated previews must not inherit the application's localhost API proxy.
export default defineConfig({
  plugins:[react(),{name:'synthetic-api-only',configureServer(server){
    server.middlewares.use('/api',(req,res)=>{
      if(req.method==='GET'&&/^\/scanner\/(?:signals|trades)\/\d+\/chart(?:\?|$)/.test(req.url||'')){
        res.setHeader('Content-Type','image/svg+xml')
        res.end('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="240"><rect width="640" height="240" fill="#111f31"/><text x="320" y="120" fill="white" text-anchor="middle">Synthetic UI fixture. No market prices requested.</text></svg>')
      }else{res.statusCode=503;res.end('Isolated preview: API forwarding is disabled')}
    })
  }}],
  server:{host:'127.0.0.1',port:4334,strictPort:true},
})
