#!/usr/bin/env node
/**
 * session-launcher.js v2 — Multi-session launcher for Page Agent MCP
 *
 * Uses the central port-manager.js to allocate ports with queuing support.
 * When all ports are busy, it waits in queue until one frees up.
 *
 * Port allocation:
 *   Calls POST http://127.0.0.1:38400/allocate with a sessionId.
 *   If allocated: spawns MCP server on the assigned port.
 *   If queued: polls POST /poll until a port frees up.
 *
 * Liveness:
 *   Sends heartbeat every 15s to POST /heartbeat.
 *   On exit (SIGINT/SIGTERM/stdin-end/parent-exit), calls POST /release.
 *
 * Usage:
 *   node scripts/session-launcher.js
 *
 * Env vars (forwarded to MCP child):
 *   LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_NAME (optional)
 *   PM_URL — port manager URL (default http://127.0.0.1:38400)
 *   PAGE_AGENT_SESSION_ID — optional session id (auto-generated if missing)
 */

import { spawn } from 'node:child_process'
import { request } from 'node:http'
import { randomUUID } from 'node:crypto'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const MCP_SERVER = resolve(__dirname, '..', 'packages', 'mcp', 'src', 'index.js')

const PM_URL = process.env.PM_URL || 'http://127.0.0.1:38400'
const PM_HOST = new URL(PM_URL).hostname
const PM_PORT = parseInt(new URL(PM_URL).port || '38400')
const HEARTBEAT_INTERVAL_MS = 15_000
const QUEUE_POLL_INTERVAL_MS = 5_000
const QUEUE_TIMEOUT_MS = 300_000 // 5 min max wait
const PARENT_CHECK_INTERVAL_MS = 5_000 // Windows: check parent every 5s

const SESSION_ID = process.env.PAGE_AGENT_SESSION_ID || `session_${randomUUID().slice(0, 8)}`

// ---- HTTP helpers ----

function httpPost(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body)
    const req = request({
      hostname: PM_HOST, port: PM_PORT, path, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(Buffer.concat(chunks).toString()) })
        } catch {
          reject(new Error(`Invalid JSON response from port manager (status ${res.statusCode})`))
        }
      })
    })
    req.on('error', reject)
    req.write(data)
    req.end()
  })
}

function httpGet(path) {
  return new Promise((resolve, reject) => {
    const req = request({
      hostname: PM_HOST, port: PM_PORT, path, method: 'GET',
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(Buffer.concat(chunks).toString()) })
        } catch {
          reject(new Error('Invalid JSON response from port manager'))
        }
      })
    })
    req.on('error', reject)
    req.end()
  })
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }

// ---- Port allocation with queue ----

async function allocatePort() {
  console.error(`[launcher] Requesting port from ${PM_URL} (session ${SESSION_ID})`)

  const { status, body } = await httpPost('/allocate', { sessionId: SESSION_ID, pid: process.pid })
  
  if (body.allocated) {
    console.error(`[launcher] Allocated port ${body.port} (lease ${body.leaseId.slice(0, 8)})`)
    return { port: body.port, leaseId: body.leaseId }
  }

  if (body.queued) {
    console.error(`[launcher] All ${body.message}`)
    console.error(`[launcher] Waiting in queue... (position ${body.position})`)
    
    // Long-poll for fulfillment
    const pollBody = { sessionId: SESSION_ID, pid: process.pid, timeoutMs: QUEUE_TIMEOUT_MS }
    const result = await httpPost('/poll', pollBody)
    
    if (result.body.allocated) {
      console.error(`[launcher] Dequeued! Port ${result.body.port} (lease ${result.body.leaseId.slice(0, 8)})`)
      return { port: result.body.port, leaseId: result.body.leaseId }
    }
    
    throw new Error(`Queue wait failed: ${result.body.error || 'unknown'}`)
  }

  throw new Error(`Port allocation failed: ${JSON.stringify(body)}`)
}

// ---- MCP child process ----

let child = null
let leaseId = null
let heartbeatTimer = null
let parentCheckTimer = null

// ---- Parent process liveness check (Windows) ----
// On Windows, SIGTERM/SIGINT are unreliable when the terminal window is closed.
// stdin 'end' may not fire. We poll the parent PID as a fallback.

function isProcessAlive(pid) {
  try {
    // process.kill(pid, 0) works cross-platform: sends no signal,
    // throws ESRCH if the process doesn't exist.
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

function startParentCheck(parentPid) {
  if (parentCheckTimer) clearInterval(parentCheckTimer)
  parentCheckTimer = setInterval(() => {
    if (!isProcessAlive(parentPid)) {
      console.error(`[launcher] Parent process (PID ${parentPid}) exited — cleaning up`)
      cleanup().then(() => process.exit(0))
    }
  }, PARENT_CHECK_INTERVAL_MS)
}

function stopParentCheck() {
  if (parentCheckTimer) {
    clearInterval(parentCheckTimer)
    parentCheckTimer = null
  }
}

// ----

function startHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer)
  heartbeatTimer = setInterval(async () => {
    try {
      await httpPost('/heartbeat', { leaseId })
    } catch {
      // heartbeat failures are non-fatal; port manager has its own timeout
    }
  }, HEARTBEAT_INTERVAL_MS)
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

async function releasePort(reason = 'session ended') {
  stopHeartbeat()
  stopParentCheck()
  if (!leaseId) return
  try {
    const { body } = await httpPost('/release', { leaseId })
    console.error(`[launcher] Port released (${reason}): ${body.released ? 'ok' : 'not found'}`)
  } catch (err) {
    console.error(`[launcher] Failed to release port: ${err.message}`)
  }
  leaseId = null
}

async function cleanup() {
  await releasePort('cleanup')
  if (child && !child.killed) {
    child.kill('SIGTERM')
  }
}

// ---- Auto-start PM if not running ----

/** Try to wake up or start the port manager. Returns true if PM is responding. */
async function ensurePortManager() {
  try {
    await httpGet('/health')
    return true
  } catch {
    console.error('[launcher] Port manager not responding. Starting...')
    const pmScript = resolve(__dirname, 'port-manager.js')
    
    const pm = spawn('node', [pmScript], {
      detached: true,
      stdio: 'ignore',
      cwd: resolve(__dirname, '..'),
    })
    pm.unref()
    
    // Wait for PM to start (up to 5s)
    for (let i = 0; i < 25; i++) {
      await sleep(200)
      try {
        await httpGet('/health')
        console.error('[launcher] Port manager started and responding.')
        return true
      } catch {}
    }
    throw new Error('Port manager failed to start within 5s')
  }
}

// ---- Main ----

async function main() {
  await ensurePortManager()
  const { port, leaseId: lid } = await allocatePort()
  leaseId = lid

  console.error(`[launcher] Starting MCP server on port ${port}`)

  // Build env for child MCP server
  const env = {
    ...process.env,
    PORT: String(port),
  }

  // Spawn the real MCP server
  child = spawn('node', [MCP_SERVER], {
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
    cwd: resolve(__dirname, '..'),
  })

  // Start heartbeat to port manager
  startHeartbeat()

  // Windows: poll parent process liveness as fallback cleanup mechanism.
  // stdin 'end' and SIGTERM are unreliable when the terminal window is closed
  // on Windows. This interval ensures we detect parent exit within 5 seconds.
  startParentCheck(process.ppid)

  // Proxy child stderr to parent stderr
  child.stderr.on('data', (d) => process.stderr.write(d))

  // Proxy stdio
  process.stdin.pipe(child.stdin)
  child.stdout.pipe(process.stdout)

  // Handle child exit
  child.on('exit', (code, signal) => {
    console.error(`[launcher] MCP server exited (code=${code}, signal=${signal})`)
    releasePort(`child exited code=${code}`).then(() => process.exit(code ?? 1))
  })

  child.on('error', async (err) => {
    console.error(`[launcher] Failed to spawn MCP server: ${err.message}`)
    await cleanup()
    process.exit(1)
  })

  // Clean up when parent exits or stdin closes
  process.on('SIGINT', async () => { await cleanup(); process.exit(0) })
  process.on('SIGTERM', async () => { await cleanup(); process.exit(0) })
  
  process.stdin.on('end', async () => {
    console.error('[launcher] stdin closed (TUI exited), releasing port')
    await cleanup()
    process.exit(0)
  })
}

main().catch(async (err) => {
  console.error(`[launcher] ${err.message}`)
  await releasePort('error')
  process.exit(1)
})
