import assert from 'node:assert/strict'
import { build } from 'esbuild'
const bundled = await build({ entryPoints: ['src/readPoller.ts'], bundle: true, write: false, platform: 'node', format: 'cjs' })
const mod = { exports: {} }
new Function('module', 'exports', bundled.outputFiles[0].text)(mod, mod.exports)
const { createReadPoller } = mod.exports
const real = { setTimeout, clearTimeout, setInterval, clearInterval, fetch: globalThis.fetch, document: globalThis.document }
let now = 0, nextId = 0, requests = [], results = [], errors = [], settled = 0
const timers = new Map(), listeners = new Set()
globalThis.setTimeout = (fn, delay) => { const id = ++nextId; timers.set(id, { fn, at: now + delay }); return id }
globalThis.clearTimeout = id => timers.delete(id)
globalThis.setInterval = (fn, delay) => { const id = ++nextId; timers.set(id, { fn, at: now + delay, delay }); return id }
globalThis.clearInterval = globalThis.clearTimeout
globalThis.document = { visibilityState: 'visible', addEventListener: (_, fn) => listeners.add(fn), removeEventListener: (_, fn) => listeners.delete(fn) }
globalThis.fetch = (url, options) => new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }))
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
const tick = async ms => {
  const end = now + ms
  while (true) {
    const due = [...timers].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0]
    if (!due) break
    const [id, timer] = due; now = timer.at
    if (timer.delay) timer.at += timer.delay; else timers.delete(id)
    timer.fn(); await flush()
  }
  now = end; await flush()
}
const visibility = value => { document.visibilityState = value; for (const fn of listeners) fn() }
const response = data => ({ ok: true, json: async () => data })
try {
  const poller = createReadPoller({ url: '/public', intervalMs: 30000,
    onData: data => { results.push(data); errors = [] }, onError: e => errors.push(e), onSettled: () => settled++ })
  poller.start(); poller.start()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].options.cache, 'no-store')
  await tick(15000) // Previously aborted at 12 seconds. Still bounded, not infinite.
  assert.equal(requests[0].options.signal.aborted, false)
  requests[0].resolve(response({ generated_at: 'original', count: 1 })); await flush()
  assert.deepEqual(results, [{ generated_at: 'original', count: 1 }])
  assert.equal(settled, 1)
  await tick(15000); assert.equal(requests.length, 2)
  void poller.refresh(); void poller.refresh()
  assert.equal(requests.length, 2) // One in flight; no periodic/manual overlap.
  await tick(20000)
  assert.equal(requests[1].options.signal.aborted, true)
  assert.deepEqual(errors, ['Refresh timed out'])
  assert.equal(results.length, 1) // Retain data, but report real timeout.
  requests[1].resolve(response({ stale: true })); await flush()
  assert.equal(results.length, 1) // Late result cannot mark the connection healthy.
  await tick(10000); assert.equal(requests.length, 3)
  requests[2].resolve(response({ count: 2 })); await flush()
  assert.equal(errors.length, 0); assert.equal(results.length, 2)
  void poller.refresh(); requests[3].resolve({ ok: false, status: 500 }); await flush()
  assert.deepEqual(errors, ['HTTP 500'])
  void poller.refresh(); requests[4].resolve({ ok: true, json: async () => { throw Error('Invalid JSON') } }); await flush()
  assert.equal(errors.at(-1), 'Invalid JSON')
  void poller.refresh(); const interrupted = requests.at(-1)
  const errorCount = errors.length
  visibility('hidden'); visibility('visible') // Foreground before aborted promise settles.
  await flush()
  assert.equal(interrupted.options.signal.aborted, true)
  assert.equal(errors.length, errorCount) // Background cancellation isn't a failed service.
  assert.equal(requests.length, 7) // Foreground starts exactly one immediate retry.
  requests[6].resolve(response({ count: 3 })); await flush()
  assert.equal(errors.length, 0)
  visibility('hidden'); await tick(60000); assert.equal(requests.length, 7)
  visibility('visible'); await flush(); assert.equal(requests.length, 8)
  void poller.refresh(true); void poller.refresh(true)
  requests[7].resolve(response({ count: 4 })); await flush()
  assert.equal(requests.length, 9) // Post-write refresh is queued, coalesced once.
  poller.stop(); requests[8].resolve(response({ afterUnmount: true })); await flush()
  assert.equal(results.length, 4)
  assert.equal(listeners.size, 0); assert.equal(timers.size, 0)
  await tick(90000); assert.equal(requests.length, 9)
  console.log('read poller: slow read, timeout, HTTP/JSON failure, recovery, foreground race, overlap and cleanup PASS')
} finally { Object.assign(globalThis, real) }
