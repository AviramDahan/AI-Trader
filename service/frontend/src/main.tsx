import React from 'react'
import ReactDOM from 'react-dom/client'
import { discoverBackend } from './runtimeConfig'
import './index.css'

async function start() {
  await discoverBackend()
  const { default: App } = await import('./App.tsx')
  ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
}
void start()
