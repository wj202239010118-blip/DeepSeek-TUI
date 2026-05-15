#!/usr/bin/env node
/**
 * port-manager.js — Central port pool manager for Page Agent MCP
 *
 * Manages a pool of TCP ports for multi-session DeepSeek TUI usage.
 * Each session requests a port lease, sends periodic heartbeats, and
 * releases the port when done. When all ports are occupied, new
 * sessions are queued and allocated in FIFO order as ports free up.
 *
 * HTTP API (default http://127.0.0.1:38400):
 *   GET  /health              → full port pool status
 *   POST /allocate            → body: {"sessionId":"..."}
 *   POST /release             → body: {"leaseId":"..."}
 *   POST /heartbeat           → body: {"leaseId":"..."}
 *   GET  /queue               → current queue status
 *   GET  /suggest             → suggest best port for manual allocation
 *   POST /poll                → long-poll for queue fulfillment
 *
 * Start:
 *   node scripts/port-manager.js
 *
 * Env vars:
 *   PM_PORT        — listen port (default 38400)
 *   PM_POOL_START  — first pool port (default 38401)
 *   PM_POOL_END    — last pool port (default 38410)
 *   PM_HEARTBEAT_TIMEOUT_MS — release after no heartbeat (default 60000)
 *   PM_CLEANUP_INTERVAL_MS  — cleanup tick (default 15000)
 */

import { createServer } from 'node:http'
import { createServer as createNetServer } from 'node:net'
import { randomUUID } from 'node:crypto'

const PM_PORT = parseInt(process.env.PM_PORT || '38400')
const POOL_START = parseInt(process.env.PM_POOL_START || '38401')
const POOL_END = parseInt(process.env.PM_POOL_END || '38410')
const HEARTBEAT_TIMEOUT_MS = parseInt(process.env.PM_HEARTBEAT_TIMEOUT_MS || '60000')
const CLEANUP_INTERVAL_MS = parseInt(process.env.PM_CLEANUP_INTERVAL_MS || '15000')
const IDLE_SHUTDOWN_MS = parseInt(process.env.PM_IDLE_SHUTDOWN_MS || '300000') // 5 min idle -> exit

// State
const pool = new Map()
for (let p = POOL_START; p <= POOL_END; p++) {
  pool.set(p, { status: 'free' })
}
const queue = []
let lastActivity = Date.now() // track for idle shutdown

function now() { return Date.now() }
function markActivity() { lastActivity = now() } // reset idle timer on any interaction

function isPortInUse(port) {
  return new Promise((resolve) => {
    const s = createNetServer()
    s.once('error', () => resolve(true))
    s.once('listening', () => { s.close(() => resolve(false)) })
    s.listen(port, '127.0.0.1')
  })
}

function json(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(data))
}

async function readBody(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(chunk)
  return Buffer.concat(chunks).toString('utf-8')
}

async function allocatePort(sessionId, pid) {
  for (const [port, info] of pool) {
    if (info.status === 'free') {
      const inUse = await isPortInUse(port)
      if (inUse) {
        pool.set(port, { status: 'allocated', sessionId: 'unknown', allocatedAt: now(), lastHeartbeat: now() })
        continue
      }
      const leaseId = randomUUID()
      pool.set(port, {
        status: 'allocated', sessionId, pid, leaseId,
        allocatedAt: now(), lastHeartbeat: now(),
      })
      console.error(`[pm] Allocated port ${port} -> ${sessionId}`)
      markActivity()
      return { allocated: true, port, leaseId }
    }
  }
  return { allocated: false }
}

function enqueue(sessionId) {
  const entry = { sessionId, resolve: null, reject: null, queuedAt: now(), timer: null }
  const promise = new Promise((r, j) => { entry.resolve = r; entry.reject = j })
  queue.push(entry)
  console.error(`[pm] Queued ${sessionId} at position ${queue.length}`)
  markActivity()
  return { promise, position: queue.length, entry }
}

async function tryFulfillQueue() {
  while (queue.length > 0) {
    const next = queue[0]
    const result = await allocatePort(next.sessionId)
    if (result.allocated) {
      queue.shift()
      next.resolve(result)
      console.error(`[pm] Fulfilled queued ${next.sessionId} -> port ${result.port}`)
    } else break
  }
}

function releasePort(leaseId, reason = 'explicit') {
  for (const [port, info] of pool) {
    if (info.leaseId === leaseId && info.status === 'allocated') {
      pool.set(port, { status: 'free' })
      console.error(`[pm] Released port ${port} (${info.sessionId}) - ${reason}`)
      markActivity()
      tryFulfillQueue()
      return true
    }
  }
  return false
}

function heartbeat(leaseId) {
  for (const [, info] of pool) {
    if (info.leaseId === leaseId && info.status === 'allocated') {
      info.lastHeartbeat = now()
      markActivity()
      return true
    }
  }
  return false
}

async function cleanupStaleLeases() {
  const cutoff = now() - HEARTBEAT_TIMEOUT_MS
  for (const [port, info] of pool) {
    if (info.status === 'allocated' && info.lastHeartbeat && info.lastHeartbeat < cutoff) {
      // PID liveness check: if the owning process is dead, force-release
      // even if the port appears in use (could be a different process).
      if (info.pid && typeof info.pid === 'number') {
        try { process.kill(info.pid, 0) } catch { releasePort(info.leaseId, `pid ${info.pid} not alive`); continue }
      }
      const inUse = await isPortInUse(port)
      if (!inUse) {
        releasePort(info.leaseId, `heartbeat timeout`)
      } else {
        info.lastHeartbeat = now()
      }
    }
  }
}
function checkIdleShutdown() {
  cleanupStaleLeases()

  // If all ports are free, no queue, and idle for too long -> exit
  const allFree = [...pool.values()].every(i => i.status === 'free')
  if (allFree && queue.length === 0 && (now() - lastActivity) > IDLE_SHUTDOWN_MS) {
    console.error('[pm] All ports idle for >5min, shutting down to free resources.')
    server.close()
    process.exit(0)
  }
}
setInterval(checkIdleShutdown, CLEANUP_INTERVAL_MS)

// HTTP server
const server = createServer(async (req, res) => {
  const u = new URL(req.url ?? '/', `http://127.0.0.1:${PM_PORT}`)
  const p = u.pathname
  try {
    if (p === '/health' && req.method === 'GET') {
      const ports = [...pool.entries()].map(([port, info]) => ({
        port, status: info.status, sessionId: info.sessionId || null,
        ageSec: info.allocatedAt ? Math.round((now() - info.allocatedAt) / 1000) : null,
        lastHbSec: info.lastHeartbeat ? Math.round((now() - info.lastHeartbeat) / 1000) : null,
      }))
      const free = ports.filter(p => p.status === 'free')
      return json(res, 200, { ok: true, poolSize: pool.size, freeCount: free.length, allocCount: ports.length - free.length, queueLen: queue.length, freePorts: free.map(p => p.port), suggested: free[0]?.port || null, ports })
    }
    if (p === '/suggest' && req.method === 'GET') {
      const free = [...pool.entries()].filter(([, i]) => i.status === 'free').map(([port]) => port)
      return json(res, 200, { suggested: free[0] || null, freePorts: free, allBusy: free.length === 0, queueLen: queue.length })
    }
    if (p === '/allocate' && req.method === 'POST') {
      const body = await readBody(req)
      let sessionId
      try { ({ sessionId } = JSON.parse(body)) } catch { return json(res, 400, { error: 'Invalid JSON' }) }
      if (!sessionId) return json(res, 400, { error: 'Missing sessionId' })
      let pid = undefined
      try { ({ pid } = JSON.parse(body)) } catch {}
      const result = await allocatePort(sessionId, pid)
      if (result.allocated) {
        return json(res, 200, { ok: true, allocated: true, queued: false, port: result.port, leaseId: result.leaseId })
      }
      const { position } = enqueue(sessionId)
      return json(res, 202, { ok: true, allocated: false, queued: true, position, message: `All ${POOL_END - POOL_START + 1} ports busy. Queued at position ${position}.` })
    }
    if (p === '/release' && req.method === 'POST') {
      const body = await readBody(req)
      let leaseId
      try { ({ leaseId } = JSON.parse(body)) } catch { return json(res, 400, { error: 'Invalid JSON' }) }
      if (!leaseId) return json(res, 400, { error: 'Missing leaseId' })
      return json(res, 200, { ok: true, released: releasePort(leaseId) })
    }
    if (p === '/heartbeat' && req.method === 'POST') {
      const body = await readBody(req)
      let leaseId
      try { ({ leaseId } = JSON.parse(body)) } catch { return json(res, 400, { error: 'Invalid JSON' }) }
      if (!leaseId) return json(res, 400, { error: 'Missing leaseId' })
      return json(res, 200, { ok: heartbeat(leaseId) })
    }
    if (p === '/queue' && req.method === 'GET') {
      const sid = u.searchParams.get('sessionId')
      const items = queue.map((q, i) => ({ position: i + 1, sessionId: q.sessionId, waitSec: Math.round((now() - q.queuedAt) / 1000) }))
      return json(res, 200, { ok: true, items, length: items.length, myPosition: sid ? (items.findIndex(i => i.sessionId === sid) + 1 || null) : null })
    }
    if (p === '/poll' && req.method === 'POST') {
      const body = await readBody(req)
      let sessionId, timeoutMs = 120000
      try {
        const parsed = JSON.parse(body)
        sessionId = parsed.sessionId
        if (parsed.timeoutMs) timeoutMs = Math.min(parsed.timeoutMs, 300000)
      } catch { return json(res, 400, { error: 'Invalid JSON' }) }
      if (!sessionId) return json(res, 400, { error: 'Missing sessionId' })
      for (const [port, info] of pool) {
        if (info.sessionId === sessionId && info.status === 'allocated')
          return json(res, 200, { ok: true, allocated: true, port, leaseId: info.leaseId })
      }
      const qIdx = queue.findIndex(q => q.sessionId === sessionId)
      if (qIdx < 0) {
        // Maybe not queued yet — retry allocation
        const result = await allocatePort(sessionId)
        if (result.allocated) return json(res, 200, { ok: true, allocated: true, ...result })
        return json(res, 404, { error: 'Session not queued and no ports free' })
      }
      const entry = queue[qIdx]
      try {
        const result = await Promise.race([
          entry.promise,
          new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), timeoutMs)),
        ])
        return json(res, 200, { ok: true, allocated: true, ...result })
      } catch {
        const idx = queue.indexOf(entry)
        if (idx >= 0) queue.splice(idx, 1)
        return json(res, 408, { error: 'Queue wait timed out' })
      }
    }
    json(res, 404, { error: 'Not found' })
  } catch (err) {
    console.error(`[pm] Error: ${err.message}`)
    json(res, 500, { error: err.message })
  }
})

server.listen(PM_PORT, '127.0.0.1', () => {
  console.error(`[pm] Port manager on http://127.0.0.1:${PM_PORT}`)
  console.error(`[pm] Pool: ${POOL_START}-${POOL_END} (${POOL_END - POOL_START + 1} ports)`)
  console.error(`[pm] Heartbeat timeout: ${HEARTBEAT_TIMEOUT_MS}ms`)
})

process.on('SIGINT', () => { server.close(); process.exit(0) })
