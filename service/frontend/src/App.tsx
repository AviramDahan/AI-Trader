import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { BackendStatusBanner, Sidebar } from './appChrome'
import { LanguageContext, ThemeContext, type ThemeMode } from './appShared'
import { ScannerDashboard } from './ScannerDashboard'
import { type Language, getT } from './i18n'
import { isMiniAppEntry, mountTelegramMiniApp } from './telegramMiniApp'
import './telegramMiniApp.css'

function DisplayShell({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const mini = isMiniAppEntry(location.search)
  return <div className={`app-container ${mini ? 'miniapp-shell' : ''}`}><Sidebar />
    <main className="main-content" style={{ display: 'flex', gap: '24px' }}><div className="app-main-column">
      {!mini && <BackendStatusBanner />}{children}
    </div></main></div>
}

function App() {
  const [language, setLanguage] = useState<Language>(() => {
    const savedLanguage = localStorage.getItem('ai_trader_language')
    return savedLanguage === 'he' || (!savedLanguage && isMiniAppEntry(window.location.search)) ? 'he' : 'en'
  })
  const [theme, setTheme] = useState<ThemeMode>(() => {
    const savedTheme = localStorage.getItem('ai_trader_theme')
    return savedTheme === 'light' ? 'light' : 'dark'
  })

  // A previously provisioned operator token may still unlock protected scanner
  // controls. Public dashboard access never depends on login or registration.
  const [operatorToken] = useState<string | null>(() => isMiniAppEntry(window.location.search) ? null : localStorage.getItem('claw_token'))
  const t = getT(language)

  useEffect(() => mountTelegramMiniApp(), [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('ai_trader_theme', theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.lang = language === 'he' ? 'he' : 'en'
    document.documentElement.dir = language === 'he' ? 'rtl' : 'ltr'
    localStorage.setItem('ai_trader_language', language)
  }, [language])

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      <LanguageContext.Provider value={{ language, setLanguage, t }}>
        <BrowserRouter basename={import.meta.env.BASE_URL}>
          <DisplayShell>
                <Routes>
                  <Route path="/" element={<Navigate to="/market?tab=signals" replace />} />
                  <Route path="/market" element={<ScannerDashboard token={operatorToken} />} />
                  <Route path="/login" element={<Navigate to="/market?tab=signals" replace />} />
                  <Route path="/register" element={<Navigate to="/market?tab=signals" replace />} />
                  <Route path="*" element={<Navigate to="/market?tab=signals" replace />} />
                </Routes>
          </DisplayShell>
        </BrowserRouter>
      </LanguageContext.Provider>
    </ThemeContext.Provider>
  )
}

export default App
