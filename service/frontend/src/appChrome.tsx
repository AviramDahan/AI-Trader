import { useEffect, useRef, useState } from 'react'
import { discoverBackend, runtimeOrigin } from './runtimeConfig'

import { Link, useLocation } from 'react-router-dom'

import { API_ORIGIN, useLanguage, useTheme } from './appShared'

function LanguageSwitcher() {
  const { language, setLanguage } = useLanguage()

  return (
    <div className="control-pill-group">
      <button
        type="button"
        onClick={() => setLanguage('en')}
        className={`control-pill ${language === 'en' ? 'active' : ''}`}
      >
        EN
      </button>
      <button
        type="button"
        onClick={() => setLanguage('he')}
        className={`control-pill ${language === 'he' ? 'active' : ''}`}
      >
        עברית
      </button>
    </div>
  )
}

function ThemeSwitcher() {
  const { theme, setTheme } = useTheme()

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      <span className={`theme-icon sun ${theme === 'light' ? 'active' : ''}`}>☼</span>
      <span className={`theme-icon moon ${theme === 'dark' ? 'active' : ''}`}>☾</span>
    </button>
  )
}

export function TopbarControls() {
  return (
    <div className="topbar-controls">
      <ThemeSwitcher />
      <LanguageSwitcher />
    </div>
  )
}

export function BackendStatusBanner() {
  const { language } = useLanguage()
  const [offline, setOffline] = useState(false)
  const [checking, setChecking] = useState(false)
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<number | null>(() => {
    const value = Number(localStorage.getItem('ai_trader_backend_last_success') || 0)
    return value > 0 ? value : null
  })
  const consecutiveFailures = useRef(0)
  const confirmedOffline = useRef(false)
  const requestInFlight = useRef(false)

  const checkBackend = async () => {
    if (requestInFlight.current) return
    requestInFlight.current = true
    setChecking(true)
    try {
      await discoverBackend()
      if (runtimeOrigin() && runtimeOrigin() !== API_ORIGIN) {
        window.location.reload()
        return
      }
      const response = await fetch(`${API_ORIGIN}/health`, {
        cache: 'no-store',
        headers: { 'serveo-skip-browser-warning': 'true' },
        signal: AbortSignal.timeout(8000)
      })
      if (!response.ok || (await response.json()).status !== 'ok') throw new Error('Unhealthy backend')
      consecutiveFailures.current = 0
      const successfulAt = Date.now()
      localStorage.setItem('ai_trader_backend_last_success', String(successfulAt))
      setLastSuccessfulAt(successfulAt)
      const reloadData = confirmedOffline.current
      confirmedOffline.current = false
      setOffline(false)
      if (reloadData) window.setTimeout(() => window.location.reload(), 100)
    } catch {
      consecutiveFailures.current += 1
      if (consecutiveFailures.current >= 2) {
        confirmedOffline.current = true
        setOffline(true)
      }
    } finally {
      requestInFlight.current = false
      setChecking(false)
    }
  }

  useEffect(() => {
    void checkBackend()
    const interval = window.setInterval(() => void checkBackend(), 10000)
    const retryWhenVisible = () => { if (document.visibilityState === 'visible') void checkBackend() }
    window.addEventListener('online', retryWhenVisible)
    document.addEventListener('visibilitychange', retryWhenVisible)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('online', retryWhenVisible)
      document.removeEventListener('visibilitychange', retryWhenVisible)
    }
  }, [])

  if (!offline) return null

  return (
    <div className="backend-status-banner" role="alert">
      <div>
        <div>{language === 'he'
          ? 'אין כרגע חיבור לשרת הנתונים. המידע יחזור אוטומטית כשהחיבור יתחדש.'
          : language === 'zh'
            ? '当前无法连接数据服务器。连接恢复后数据会自动返回。'
            : 'The data server is currently unavailable. Information will return automatically when the connection recovers.'}</div>
        {lastSuccessfulAt && <small className="backend-last-success">
          {language === 'he' ? 'חיבור תקין אחרון' : language === 'zh' ? '最近成功连接' : 'Last successful connection'}: {' '}
          {new Date(lastSuccessfulAt).toLocaleString(language === 'he' ? 'he-IL' : language === 'zh' ? 'zh-CN' : 'en-GB')}
        </small>}
      </div>
      <button type="button" className="btn btn-secondary" disabled={checking} onClick={() => void checkBackend()}>
        {checking
          ? (language === 'he' ? 'בודק…' : language === 'zh' ? '检查中…' : 'Checking…')
          : (language === 'he' ? 'בדיקה מחדש' : language === 'zh' ? '重试' : 'Retry')}
      </button>
    </div>
  )
}

export function Sidebar() {
  const location = useLocation()
  const { language } = useLanguage()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const navItems = [
    { path: '/market?tab=signals', icon: '📊', label: language === 'he' ? 'סיגנלים' : 'Signals' },
    { path: '/market?tab=trades', icon: '🧾', label: language === 'he' ? 'עסקאות דמו' : 'Demo trades' },
    { path: '/market?tab=results', icon: '📈', label: language === 'he' ? 'תוצאות' : 'Results' },
    { path: '/market?tab=news', icon: '🗞️', label: language === 'he' ? 'חדשות' : 'News' },
    { path: '/market?tab=status', icon: '⚙️', label: language === 'he' ? 'מצב הסורק' : 'Scanner status' },
  ]

  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname, location.search])

  return (
    <div className={`sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`}>
      <div className="sidebar-header">
        <div className="logo">
          <div className="logo-icon">CT</div>
          <span className="logo-text">AI-Trader</span>
        </div>
        <button
          type="button"
          className="mobile-nav-toggle"
          aria-expanded={mobileMenuOpen}
          aria-label={language === 'he' ? 'פתיחת תפריט' : 'Open navigation'}
          onClick={() => setMobileMenuOpen((current) => !current)}
        >
          {mobileMenuOpen ? '×' : '☰'}
        </button>
      </div>

      <nav className="nav-section">
        <div className="nav-section-title">{language === 'he' ? 'ניווט' : language === 'zh' ? '导航' : 'Navigation'}</div>
        {navItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`nav-link ${(location.pathname + location.search) === item.path || (item.path.endsWith('signals') && location.pathname === '/market' && !location.search) ? 'active' : ''}`}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>

      <div className="sidebar-account" style={{ marginTop: 'auto' }}>
        <div className="scanner-sidebar-notice">
          <strong>{language === 'he' ? 'מסחר מדומה בלבד' : 'PAPER TRADING ONLY'}</strong>
          <span>{language === 'he' ? 'אין חיבור לברוקר ואין מסחר בכסף אמיתי.' : 'No broker connection and no real-money trading.'}</span>
        </div>
      </div>
    </div>
  )
}
