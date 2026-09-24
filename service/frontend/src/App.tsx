import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { BackendStatusBanner, Sidebar, TopbarControls } from './appChrome'
import { LanguageContext, ThemeContext, type ThemeMode } from './appShared'
import { ScannerDashboard } from './ScannerDashboard'
import { type Language, getT } from './i18n'

function App() {
  const [language, setLanguage] = useState<Language>(() => {
    const savedLanguage = localStorage.getItem('ai_trader_language')
    return savedLanguage === 'he' ? 'he' : 'en'
  })
  const [theme, setTheme] = useState<ThemeMode>(() => {
    const savedTheme = localStorage.getItem('ai_trader_theme')
    return savedTheme === 'light' ? 'light' : 'dark'
  })

  // A previously provisioned operator token may still unlock protected scanner
  // controls. Public dashboard access never depends on login or registration.
  const [operatorToken] = useState<string | null>(() => localStorage.getItem('claw_token'))
  const t = getT(language)

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
          <div className="app-container">
            <Sidebar />

            <main className="main-content" style={{ display: 'flex', gap: '24px' }}>
              <div className="app-main-column">
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '20px' }}>
                  <TopbarControls />
                </div>

                <BackendStatusBanner />

                <Routes>
                  <Route path="/" element={<Navigate to="/market?tab=signals" replace />} />
                  <Route path="/market" element={<ScannerDashboard token={operatorToken} />} />
                  <Route path="/login" element={<Navigate to="/market?tab=signals" replace />} />
                  <Route path="/register" element={<Navigate to="/market?tab=signals" replace />} />
                  <Route path="*" element={<Navigate to="/market?tab=signals" replace />} />
                </Routes>
              </div>
            </main>
          </div>
        </BrowserRouter>
      </LanguageContext.Provider>
    </ThemeContext.Provider>
  )
}

export default App
