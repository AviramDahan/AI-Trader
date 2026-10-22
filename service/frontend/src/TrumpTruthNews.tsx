import { useEffect, useState } from 'react'
import { API_ORIGIN } from './appShared'
import './TrumpTruthNews.css'

type Media = { status: 'available' | 'unavailable' | 'marker_only' | 'disabled'; kind: 'photo' | 'video' | null; asset_token?: string }
export type TruthPost = { id: string; truth_post_id: string; truth_url: string; relay_url: string; source_excerpt: string;
  translation_status: 'translated' | 'unavailable' | 'media_only' | 'link_only' | 'not_retained'; text_he: string | null;
  relay_published_at: string; observed_at: string; sent_at: string; is_repost: boolean; has_media: boolean; media: Media }
export type TruthArchive = { version: 1; status: 'READY' | 'UNAVAILABLE'; generated_at: string | null; items: TruthPost[]; next_cursor: string | null }
const postID = /^[1-9][0-9]{15,19}$/
const time = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d\d-\d\dT.*(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value))

export function parseTruthArchive(raw: unknown): TruthArchive {
  const unavailable: TruthArchive = { version: 1, status: 'UNAVAILABLE', generated_at: null, items: [], next_cursor: null }
  if (!raw || typeof raw !== 'object') return unavailable
  const page = raw as Record<string, any>
  if (page.version !== 1 || page.status !== 'READY' || !time(page.generated_at) || !Array.isArray(page.items) || page.items.length > 20 ||
    !(page.next_cursor === null || typeof page.next_cursor === 'string' && postID.test(page.next_cursor))) return unavailable
  const items: TruthPost[] = []
  for (const row of page.items) {
    if (!row || row.source_kind !== 'trump_truth_relay_v1' || row.source_verification !== 'relay_only' || row.delivery_status !== 'sent' ||
      typeof row.truth_post_id !== 'string' || !postID.test(row.truth_post_id) || row.id !== `trump-truth:${row.truth_post_id}` ||
      row.truth_url !== `https://truthsocial.com/@realDonaldTrump/${row.truth_post_id}` ||
      typeof row.relay_url !== 'string' || !/^https:\/\/t\.me\/realdonaldtrump_truth\/[1-9][0-9]*$/.test(row.relay_url) ||
      row.original_published_at !== null || !time(row.relay_published_at) || !time(row.observed_at) || !time(row.sent_at) ||
      Date.parse(row.relay_published_at) > Date.parse(row.observed_at) || Date.parse(row.observed_at) > Date.parse(row.sent_at) ||
      Date.parse(row.sent_at) > Date.parse(page.generated_at) || typeof row.source_excerpt !== 'string' || row.source_excerpt.length > 3200 ||
      typeof row.is_repost !== 'boolean' || typeof row.has_media !== 'boolean' ||
      !['translated', 'unavailable', 'media_only', 'link_only', 'not_retained'].includes(row.translation_status) ||
      (row.translation_status === 'translated' ? typeof row.text_he !== 'string' || !/[\u0590-\u05ff]/.test(row.text_he) || row.text_he.length > 2400 : row.text_he !== null)) continue
    let media: Media = { status: row.has_media ? 'marker_only' : 'unavailable', kind: null }
    if (row.media && ['unavailable', 'marker_only', 'disabled'].includes(row.media.status)) media = { status: row.media.status, kind: null }
    if (row.media?.version === 'trump_truth_media_v1' && row.media?.status === 'available' && ['photo', 'video'].includes(row.media.kind) &&
      typeof row.media.asset_token === 'string' && /^[a-f0-9]{64}$/.test(row.media.asset_token) &&
      row.media.mime_type === (row.media.kind === 'photo' ? 'image/jpeg' : 'video/mp4') && Number.isInteger(row.media.bytes) &&
      row.media.bytes > 0 && row.media.bytes <= (row.media.kind === 'photo' ? 8 : 24) * 1024 * 1024)
      media = { status: 'available', kind: row.media.kind, asset_token: row.media.asset_token }
    items.push({ id: row.id, truth_post_id: row.truth_post_id, truth_url: row.truth_url, relay_url: row.relay_url,
      source_excerpt: row.source_excerpt, translation_status: row.translation_status, text_he: row.text_he,
      relay_published_at: row.relay_published_at, observed_at: row.observed_at, sent_at: row.sent_at,
      is_repost: row.is_repost, has_media: row.has_media, media })
  }
  return { version: 1, status: 'READY', generated_at: page.generated_at, items, next_cursor: page.next_cursor }
}

function TruthCard({ item, he }: { item: TruthPost; he: boolean }) {
  const [mediaFailed, setMediaFailed] = useState(false)
  const text = (a: string, b: string) => he ? a : b
  const asset = item.media.status === 'available' && item.media.asset_token && !mediaFailed ? `${API_ORIGIN}/api/scanner/trump-media/${item.media.asset_token}` : null
  const fallback = item.translation_status === 'not_retained' ? ['התרגום השמור אינו זמין. ההיסטוריה אינה משוחזרת ולא מתבצע תרגום בבקשת התצוגה.', 'The retained translation is unavailable. History is not reconstructed or translated on this read.'] :
    item.translation_status === 'link_only' ? ['שיתוף מחדש ללא גוף הפוסט בדיווח הממסר. התוכן זמין בקישור המקורי.', 'A repost without body text in the relay. Open the original post.'] :
      item.translation_status === 'media_only' ? ['פוסט ללא קטע טקסט לתרגום. אין תמלול או תיאור AI של המדיה.', 'No source text to translate. No AI media transcript or description was generated.'] :
        ['התרגום לעברית אינו זמין כרגע. התוכן זמין בקישור לפוסט המקורי.', 'Hebrew translation is unavailable. Open the original post for the content.']
  return <article className="truth-news-card" data-truth-post={item.truth_post_id}>
    <header><h4>{text('טראמפ · Truth Social', 'Trump · Truth Social')}</h4>{item.is_repost && <span>{text('שיתוף מחדש', 'Repost')}</span>}</header>
    <section className="truth-news-language" aria-label="עברית / Hebrew" lang="he" dir="rtl">
      <h5>עברית · Hebrew</h5>
      {item.translation_status === 'translated' ? <><small>תרגום AI לעברית של קטע הדיווח — לא אימות עובדות</small><small className="truth-news-language-note" lang="en" dir="ltr">AI Hebrew translation of the relay excerpt — not fact verification.</small><p className="truth-news-body" lang="he" dir="rtl">{item.text_he}</p></> : <p className="truth-news-status">{fallback[0]}</p>}
    </section>
    <section className="truth-news-language truth-news-source-panel" aria-label="English / original relay excerpt" lang="en" dir="ltr">
      <h5>English · קטע הדיווח בשפת המקור</h5>
      <small>Original-language relay excerpt — not an independently verified primary post or AI-generated English.</small>
      {item.source_excerpt ? <p className="truth-news-original" lang="en" dir="ltr">{item.source_excerpt}</p> : <p className="truth-news-status">No source body text was retained. No English caption, transcript or missing repost body is invented.</p>}
      {item.translation_status !== 'translated' && <p className="truth-news-status">{fallback[1]}</p>}
    </section>
    {asset && (item.media.kind === 'photo' ? <img className="truth-news-media" src={asset} alt={text('תמונה שצורפה בדיווח הממסר; התוכן לא אומת', 'Image attached by the relay; content unverified')} loading="lazy" referrerPolicy="no-referrer" onError={() => setMediaFailed(true)} /> :
      <video className="truth-news-media" src={asset} controls playsInline preload="none" onError={() => setMediaFailed(true)} />)}
    {item.has_media && !asset && <div className="truth-news-status"><p lang="he" dir="rtl">המדיה אינה זמינה בתצוגה השמורה. אפשר לצפות במקור; אין לנחש את תוכנה.</p><p lang="en" dir="ltr">Media is unavailable in this archive. Open the source; its content is not inferred.</p></div>}
    <footer><p lang="he" dir="rtl">דיווח מערוץ מעקב; לא אומת מול החשבון המקורי. זמן הפרסום המקורי: לא אומת.</p><p lang="en" dir="ltr">Relay-channel report, not verified against the original account. Original publication time: not verified.</p>
      <dl><div><dt>{text('דווח בערוץ', 'Relay published')}</dt><dd><time dateTime={item.relay_published_at}><bdi>{item.relay_published_at}</bdi></time></dd></div>
        <div><dt>{text('נצפה לראשונה', 'First observed')}</dt><dd><time dateTime={item.observed_at}><bdi>{item.observed_at}</bdi></time></dd></div>
        <div><dt>{text('נרשם כנשלח', 'Recorded sent')}</dt><dd><time dateTime={item.sent_at}><bdi>{item.sent_at}</bdi></time></dd></div></dl>
      <nav aria-label={text('מקורות הפוסט', 'Post sources')}><a href={item.truth_url} target="_blank" rel="noopener noreferrer">{text('הפוסט המלא ב־Truth Social', 'Full Truth Social post')}</a><a href={item.relay_url} target="_blank" rel="noopener noreferrer">{text('דיווח ערוץ המעקב', 'Relay report')}</a></nav>
    </footer>
  </article>
}

export function TrumpTruthNewsView({ he, data, error = '', loading = false, onMore }: { he: boolean; data: TruthArchive; error?: string; loading?: boolean; onMore?: () => void }) {
  const text = (a: string, b: string) => he ? a : b
  const stale = data.generated_at && Date.now() - Date.parse(data.generated_at) > 180000
  return <section className="truth-news" dir={he ? 'rtl' : 'ltr'} aria-labelledby="truth-news-heading">
    <h3 id="truth-news-heading">{text('טראמפ · ארכיון דיווחי Truth Social', 'Trump · Truth Social relay archive')}</h3>
    <p>{text('מדור נפרד מחדשות המניות ומהסינון הפיננסי. הודעות בעברית ובדו־לשוני שנרשמו כנשלחות בלבד, עד 7 ימים; עברית וקטע המקור מוצגים יחד, ללא המלצת השקעה או סינון לפי השפעת שוק.', 'Separate from stock news and financial filters. Only Hebrew/bilingual notices recorded as sent, up to 7 days; Hebrew and the actual source excerpt appear together, with no investment advice or market-impact filter.')}</p>
    {(error || data.status !== 'READY') && <p role="alert">{text('ארכיון הפוסטים אינו זמין כרגע. זו אינה הוכחה שאין פוסטים חדשים.', 'The post archive is unavailable. This does not prove there are no new posts.')}</p>}
    {stale && <p role="status">{text('תצוגה שמורה — זמן הקריאה ישן; אין אישור לעדכניות הממסר.', 'Retained view — the read is stale; relay freshness is not verified.')}</p>}
    <div className="truth-news-grid">{data.items.map(item => <TruthCard key={item.id} item={item} he={he} />)}</div>
    {data.status === 'READY' && !data.items.length && <p role="status">{text('אין כרגע הודעות עברית שנשלחו וזמינות בארכיון הזה. הודעות ישנות בשפת המקור אינן מוצגות מחדש.', 'No sent Hebrew notices are available in this archive. Old original-language notices are not republished.')}</p>}
    {data.generated_at && <small>{text('הארכיון נקרא ב־', 'Archive read at ')}<bdi>{data.generated_at}</bdi></small>}
    {data.next_cursor && onMore && <button type="button" disabled={loading} onClick={onMore}>{loading ? text('טוען…', 'Loading…') : text('הצג הודעות קודמות', 'Show earlier notices')}</button>}
  </section>
}

export function TrumpTruthNews({ he, initial }: { he: boolean; initial: unknown }) {
  const [data, setData] = useState(() => parseTruthArchive(initial))
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  useEffect(() => { setData(parseTruthArchive(initial)); setError('') }, [initial])
  async function more() {
    if (loading || !data.next_cursor || data.items.length >= 100) return
    const cursor = data.next_cursor
    setLoading(true); setError('')
    try {
      const response = await fetch(`${API_ORIGIN}/api/scanner/trump-posts?limit=20&before=${encodeURIComponent(cursor)}`, { cache: 'no-store', signal: AbortSignal.timeout(8000) })
      if (!response.ok) throw new Error('archive_unavailable')
      const page = parseTruthArchive(await response.json())
      if (page.status !== 'READY' || page.next_cursor === cursor) throw new Error('archive_unavailable')
      setData(current => {
        if (current.next_cursor !== cursor) return current // A newer dashboard read replaced this page.
        const merged = [...current.items, ...page.items.filter(item => !current.items.some(old => old.id === item.id))].slice(0, 100)
        return { ...current, items: merged, next_cursor: merged.length >= 100 ? null : page.next_cursor }
      })
    } catch { setError('archive_unavailable') } finally { setLoading(false) }
  }
  return <TrumpTruthNewsView he={he} data={data} error={error} loading={loading} onMore={() => void more()} />
}
