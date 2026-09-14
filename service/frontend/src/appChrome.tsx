import { useEffect, useRef, useState } from 'react'
import { discoverBackend, runtimeOrigin } from './runtimeConfig'

import { Link, useLocation } from 'react-router-dom'

import { API_ORIGIN, AgentName, type AgentInfo, hasPermission, isVerifiedAgent, useLanguage, useTheme } from './appShared'

export function Toast({ message, type, onClose }: { message: string, type: 'success' | 'error', onClose: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onClose, 3000)
    return () => clearTimeout(timer)
  }, [onClose])

  return <div className={`toast ${type}`}>{message}</div>
}

export type NotificationCounts = {
  discussion: number
  strategy: number
  experiment: number
}

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
  const previouslyOffline = useRef(false)

  const checkBackend = async () => {
    await discoverBackend()
    if (runtimeOrigin() && runtimeOrigin() !== API_ORIGIN) {
      window.location.reload()
      return
    }
    try {
      const response = await fetch(`${API_ORIGIN}/health`, { cache: 'no-store', signal: AbortSignal.timeout(8000) })
      if (!response.ok || (await response.json()).status !== 'ok') throw new Error('Unhealthy backend')
      setOffline(false)
      if (previouslyOffline.current) window.location.reload()
    } catch {
      previouslyOffline.current = true
      setOffline(true)
    }
  }

  useEffect(() => {
    void checkBackend()
    const interval = window.setInterval(() => void checkBackend(), 30000)
    return () => window.clearInterval(interval)
  }, [])

  if (!offline) return <PaperActivityPanel />

  return (
    <div className="backend-status-banner" role="alert">
      <span>
        {language === 'he'
          ? 'אין כרגע חיבור לשרת הנתונים. המידע יחזור אוטומטית כשהחיבור יתחדש.'
          : language === 'zh'
            ? '当前无法连接数据服务器。连接恢复后数据会自动返回。'
            : 'The data server is currently unavailable. Information will return automatically when the connection recovers.'}
      </span>
      <button type="button" className="btn btn-secondary" onClick={() => void checkBackend()}>
        {language === 'he' ? 'בדיקה מחדש' : language === 'zh' ? '重试' : 'Retry'}
      </button>
    </div>
  )
}

type ScannerActivity = {
  enabled: boolean; stale: boolean; status: string; model: string; next_scan_at?: number;
  last_scan_at?: number; universe_count?: number; data_count?: number; candidates_count?: number;
  signals_published?: number; last_signal?: { ticker: string; action: string; confidence: number };
  ai_reviews?: { ticker: string; action: string; confidence: number }[];
  events?: { at: number; action: string; reason: string }[];
}

function PaperActivityPanel() {
  const { language } = useLanguage()
  const he = language === 'he'
  const [activity, setActivity] = useState<ScannerActivity | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const response = await fetch(`${API_ORIGIN}/api/runtime/activity`, { cache: 'no-store', signal: AbortSignal.timeout(8000) })
        if (!response.ok) throw new Error('Unavailable')
        const value = await response.json()
        if (active) { setActivity(value); setFailed(false) }
      } catch { if (active) setFailed(true) }
    }
    void load()
    const interval = window.setInterval(() => void load(), 15000)
    return () => { active = false; window.clearInterval(interval) }
  }, [])
  const time = (value?: number) => value ? new Date(value * 1000).toLocaleString(he ? 'he-IL' : 'en-GB') : '—'
  const state = failed ? (he ? 'סטטוס לא זמין' : 'Status unavailable')
    : !activity?.enabled ? (he ? 'לא פעיל' : 'Disabled')
    : activity.stale ? (he ? 'הסוכן לא התעדכן בזמן' : 'Agent heartbeat overdue')
    : activity.status === 'scanning' ? (he ? 'סורק מניות' : 'Scanning stocks')
    : activity.status === 'error' ? (he ? 'תקלה — המסחר מושהה' : 'Error — trading paused')
    : (he ? 'ממתין למחזור הבא' : 'Waiting for next cycle')
  return <details className="paper-activity-panel" data-testid="paper-activity">
    <summary>{he ? 'סורק מניות · מסחר מדומה בלבד' : 'US STOCK SCANNER · PAPER ONLY'} · {state}</summary>
    <p>{he ? 'סריקה אחרונה' : 'Last scan'}: {time(activity?.last_scan_at)} | {he ? 'סריקה הבאה' : 'Next scan'}: {time(activity?.next_scan_at)}</p>
    <p>{he ? 'יקום מניות' : 'Universe'}: {activity?.universe_count || 0} | {he ? 'נתונים תקינים' : 'Fresh datasets'}: {activity?.data_count || 0} | {he ? 'מועמדים' : 'Candidates'}: {activity?.candidates_count || 0}</p>
    <p>{he ? 'אותות חזקים בסריקה האחרונה' : 'Strong signals in last scan'}: {activity?.signals_published || 0}</p>
    {activity?.last_signal && <p>{he ? 'אות אחרון' : 'Last signal'}: {activity.last_signal.ticker} {activity.last_signal.action} ({Math.round(activity.last_signal.confidence * 100)}%)</p>}
    {!!activity?.ai_reviews?.length && <p>{he ? 'בדיקות AI אחרונות' : 'Recent AI reviews'}: {activity.ai_reviews.map(item => `${item.ticker} ${item.action} ${Math.round(item.confidence * 100)}%`).join(' · ')}</p>}
    <p>{he ? 'אות מתפרסם רק עם מחיר תוך־יומי וחדשות עדכניים, ובשעות המסחר. HOLD ודחיות מוצגים בסטטוס אך אינם יוצרים פוזיציה.' : 'A signal is published only with a fresh intraday quote and recent relevant news during market hours. HOLD/rejections remain status events and do not create positions.'}</p>
    <ol>{activity?.events?.slice(0, 8).map((item, index) => <li key={`${item.at}-${index}`}>
      <time>{time(item.at)}</time> · {item.action}: {item.reason}
    </li>)}</ol>
  </details>
}

export function Sidebar({
  token,
  agentInfo,
  onLogout,
  notificationCounts,
  onMarkCategoryRead
}: {
  token: string | null
  agentInfo: AgentInfo | null
  onLogout: () => void
  notificationCounts: NotificationCounts
  onMarkCategoryRead: (category: 'discussion' | 'strategy' | 'experiment') => void
}) {
  const location = useLocation()
  const { t, language } = useLanguage()
  const [showToken, setShowToken] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const canUseExperiments = hasPermission(agentInfo, 'experiment_admin')
  const canUseResearchExports = hasPermission(agentInfo, 'research_exports')
  const canUseTeamMissionAdmin = hasPermission(agentInfo, 'team_mission_admin')
  const agentToken = agentInfo?.token

  const navItems = [
    { path: '/financial-events', icon: '🗞️', label: language === 'he' ? 'אירועים פיננסיים' : language === 'zh' ? '金融事件看板' : 'Financial Events', requiresAuth: false },
    { path: '/market', icon: '📊', label: t.nav.signals, requiresAuth: false },
    { path: '/leaderboard', icon: '🏆', label: language === 'he' ? 'דירוג סוחרים' : language === 'zh' ? '排行榜' : 'Leaderboard', requiresAuth: false },
    { path: '/challenges', icon: '⚔️', label: language === 'he' ? 'אתגרים' : language === 'zh' ? '挑战赛' : 'Challenges', requiresAuth: false },
    ...(canUseTeamMissionAdmin ? [{ path: '/team-missions', icon: '▦', label: language === 'he' ? 'משימות צוות' : language === 'zh' ? '团队任务' : 'Team Missions', requiresAuth: true }] : []),
    ...(canUseExperiments ? [{ path: '/experiments', icon: '◇', label: language === 'he' ? 'ניסויים' : language === 'zh' ? '实验' : 'Experiments', requiresAuth: true, badge: notificationCounts.experiment, category: 'experiment' as const }] : []),
    ...(canUseResearchExports ? [{ path: '/research-exports', icon: '⇩', label: language === 'he' ? 'ייצוא מחקר' : language === 'zh' ? '研究导出' : 'Research Exports', requiresAuth: true }] : []),
    { path: '/copytrading', icon: '📋', label: language === 'he' ? 'העתקת מסחר' : language === 'zh' ? '跟单' : 'Copy Trading', requiresAuth: true },
    { path: '/strategies', icon: '📈', label: t.nav.strategies, requiresAuth: false, badge: notificationCounts.strategy, category: 'strategy' as const },
    { path: '/discussions', icon: '💬', label: t.nav.discussions, requiresAuth: false, badge: notificationCounts.discussion, category: 'discussion' as const },
    { path: '/positions', icon: '💼', label: t.nav.positions, requiresAuth: false },
    { path: '/trade', icon: '💰', label: t.nav.trade, requiresAuth: true },
    { path: '/exchange', icon: '🎁', label: t.nav.exchange, requiresAuth: true },
  ]

  useEffect(() => {
    const activeItem = navItems.find((item) => item.path === location.pathname)
    if (activeItem?.category && (activeItem.badge || 0) > 0) {
      onMarkCategoryRead(activeItem.category)
    }
  }, [location.pathname, notificationCounts.discussion, notificationCounts.strategy, notificationCounts.experiment])

  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

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
            className={`nav-link ${location.pathname === item.path || location.pathname.startsWith(`${item.path}/`) ? 'active' : ''}`}
            title={!token && item.requiresAuth ? (language === 'he' ? 'נדרשת התחברות' : language === 'zh' ? '登录后可用' : 'Login required') : undefined}
            onClick={() => {
              if (item.category && (item.badge || 0) > 0) {
                onMarkCategoryRead(item.category)
              }
            }}
          >
            <span className="nav-icon">{item.icon}</span>
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: '8px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>{item.label}</span>
                {(item.badge || 0) > 0 && (
                  <span style={{
                    minWidth: '18px',
                    height: '18px',
                    padding: '0 6px',
                    borderRadius: '999px',
                    background: '#ef4444',
                    color: '#fff',
                    fontSize: '11px',
                    fontWeight: 700,
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    lineHeight: 1
                  }}>
                    {item.badge && item.badge > 99 ? '99+' : item.badge}
                  </span>
                )}
              </span>
              {!token && item.requiresAuth && (
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {language === 'he' ? 'התחברות' : language === 'zh' ? '需登录' : 'Login'}
                </span>
              )}
            </span>
          </Link>
        ))}
      </nav>

      <div className="sidebar-account" style={{ marginTop: 'auto' }}>
        {token && agentInfo ? (
          <div style={{ padding: '16px', background: 'var(--bg-tertiary)', borderRadius: '12px' }}>
            <div className="user-info">
              <div className="user-avatar">{agentInfo.name?.charAt(0) || 'A'}</div>
              <div className="user-details">
                <AgentName name={agentInfo.name} verified={isVerifiedAgent(agentInfo)} className="user-name" />
                <span className="user-points">{agentInfo.points} {language === 'he' ? 'נקודות' : language === 'zh' ? '积分' : 'points'}</span>
              </div>
              {agentInfo.cash !== undefined && (
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {language === 'he' ? 'מזומן: ' : language === 'zh' ? '现金: ' : 'Cash: '}
                  <span style={{ color: 'var(--accent-primary)', fontWeight: 500 }}>
                    ${agentInfo.cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
              )}
            </div>

            {agentToken && (
              <div style={{ marginTop: '12px', padding: '8px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {language === 'he' ? 'אסימון API (לחיצה להעתקה)' : language === 'zh' ? 'API Token (点击复制)' : 'API Token (Click to copy)'}
                  </div>
                  <button
                    onClick={() => setShowToken(!showToken)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      fontSize: '11px',
                      padding: '2px 4px'
                    }}
                  >
                    {showToken ? '👁️' : '🙈'}
                  </button>
                </div>
                <div
                  style={{
                    fontSize: '11px',
                    fontFamily: 'monospace',
                    color: 'var(--accent-primary)',
                    cursor: 'pointer',
                    wordBreak: 'break-all'
                  }}
                  onClick={() => {
                    navigator.clipboard.writeText(agentToken)
                    alert(language === 'he' ? 'האסימון הועתק ללוח' : language === 'zh' ? 'Token 已复制到剪贴板' : 'Token copied to clipboard')
                  }}
                >
                  {showToken ? agentToken : agentToken.substring(0, 10) + '***'}
                </div>
              </div>
            )}

            <button
              onClick={onLogout}
              className="btn btn-ghost"
              style={{ width: '100%', marginTop: '12px', justifyContent: 'center' }}
            >
              {language === 'he' ? 'התנתקות' : language === 'zh' ? '退出登录' : 'Logout'}
            </button>
          </div>
        ) : (
          <div style={{ padding: '16px', background: 'var(--bg-tertiary)', borderRadius: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <div style={{ fontWeight: 600, marginBottom: '6px' }}>
                {language === 'he' ? 'מצב אורח' : language === 'zh' ? '游客模式' : 'Guest Mode'}
              </div>
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                {language === 'he'
                  ? 'אפשר לצפות בשווקים, בדירוג, באסטרטגיות ובדיונים. יש להתחבר כדי לבצע מסחר מדומה, להעתיק עסקאות ולהמיר נקודות.'
                  : language === 'zh'
                  ? '现在可以直接查看交易市场、排行榜、策略和讨论。登录后可交易、跟单和兑换积分。'
                  : 'You can browse markets, leaderboard, strategies, and discussions now. Login to trade, copy, and exchange points.'}
              </div>
            </div>
            <Link to="/login" className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
              {language === 'he' ? 'התחברות / הרשמה' : language === 'zh' ? '登录 / 注册' : 'Login / Register'}
            </Link>
            <Link to="/market" className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center' }}>
              {language === 'he' ? 'צפייה בשוק' : language === 'zh' ? '先看看市场' : 'Browse Market'}
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}
