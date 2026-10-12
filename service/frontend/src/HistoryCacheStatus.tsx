type Cache = Record<string, any>

export function HistoryCacheStatus({ cache, he }: { cache?: Cache, he: boolean }) {
  const t = (a: string, b: string) => he ? a : b
  const states: Record<string, string> = {
    cache_hit: t('מטמון תקין', 'Cache hit'), refreshed: t('רוענן', 'Refreshed'),
    incremental_refresh: t('ריענון חלקי הושלם', 'Incremental refresh completed'),
    partial_fallback: t('נתונים עדכניים עם חוסרים נקודתיים', 'Current data with isolated gaps'),
    refresh_failed_cache_current: t('הריענון נכשל; תאריך נתוני המטמון עדכני', 'Refresh failed; cached session date is current'),
    stale_fallback: t('שימוש בנתונים היסטוריים ישנים לאחר כשל ריענון', 'Older history retained after refresh failure'),
  }
  const errors: Record<string, string> = {
    incomplete_refresh: t('הספק לא החזיר כיסוי מלא לריענון', 'Provider refresh coverage incomplete'),
    provider_refresh_failed: t('ריענון הספק נכשל', 'Provider refresh failed'),
  }
  return <div className="history-cache-status">
    <p>{t('מטמון היסטורי', 'History cache')}: {cache ? states[cache.status] || cache.status || '—' : '—'} · {t('גיל הורדת המטמון', 'Cache download age')}: <bdi>{cache?.age_seconds != null ? `${(cache.age_seconds / 3600).toFixed(1)}h` : '—'}</bdi></p>
    {cache?.requested_symbols != null && <>
      <p>{t('נתונים עדכניים ליום המסחר שהושלם', 'Data current for completed session')}: <bdi>{cache.expected_session || '—'}</bdi> · <bdi>{cache.current_symbols}/{cache.requested_symbols}</bdi></p>
      {!!cache.lagging_symbol_count && <p>{t('סימולים עם יום חסר', 'Symbols missing a completed day')}: <bdi>{(cache.lagging_symbols || []).join(', ')}</bdi> · {cache.lagging_symbol_count}</p>}
      {!!cache.missing_symbol_count && <p>{t('סימולים ללא נתונים', 'Symbols without data')}: <bdi>{(cache.missing_symbols || []).join(', ')}</bdi> · {cache.missing_symbol_count}</p>}
      {!!cache.missing_symbol_count && <p>{t('היסטוריה חסרה אינה קביעה שמחיר תוך־יומי מיושן. חוסר ללא אבחון מפורט נשאר לא ידוע.', 'Missing history does not assert a stale intraday quote. A gap without detailed diagnostics remains unknown.')}</p>}
      {cache.symbol_details_clipped && <p>{t('מוצגים עד 50 סימולים בכל רשימת חוסרים.', 'Up to 50 symbols shown in each gap list.')}</p>}
    </>}
    {cache?.refresh_error_code && <p>{errors[cache.refresh_error_code] || t('כשל ריענון', 'Refresh failure')} · <bdi>{cache.refresh_error_type}</bdi> · {t('נתקבלו / נדרשו לריענון', 'Received / requested for refresh')}: <bdi>{cache.refresh_received_symbols}/{cache.refresh_requested_symbols}</bdi></p>}
    {Object.entries(cache?.history_gap_details || {}).map(([symbol, detail]: [string, any]) => <p key={symbol}>
      <bdi>{symbol}</bdi>: {detail.reason === 'insufficient_completed_history'
        ? t('היסטוריה קצרה מדי לניתוח טכני', 'Insufficient history for technical analysis')
        : detail.reason === 'provider_returned_no_rows'
          ? t('הספק לא החזיר נרות; הסיבה אינה ידועה', 'Provider returned no bars; cause unknown')
          : t('מבנה נתוני הספק אינו תקין', 'Invalid provider history shape')}
      {detail.completed_bars != null && <> · <bdi>{detail.completed_bars}/{detail.required_bars}</bdi> {t('נרות יומיים שהושלמו', 'completed daily bars')}</>}
    </p>)}
  </div>
}
