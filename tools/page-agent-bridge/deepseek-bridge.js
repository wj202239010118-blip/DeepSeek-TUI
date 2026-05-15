#!/usr/bin/env node
/**
 * deepseek-bridge.js v2 — HTTP bridge daemon for DeepSeek TUI
 *
 * Architecture:
 *   1. Allocates a port from the central port-manager.js (http://127.0.0.1:38400)
 *   2. Spawns the Page Agent MCP server as a child process on the allocated port
 *   3. Exposes a minimal HTTP API so DeepSeek TUI can invoke browser tools via curl
 *
 * HTTP API (on BRIDGE_PORT, default 38406):
 *   GET  /health          → {"ok":true,"connected":bool,"port":PORT}
 *   POST /execute         → body: {"tool":"browser_open_tab","args":{"url":"..."}}
 *   POST /stop            → stop current task
 *
 * Start (standalone mode):
 *   node scripts/deepseek-bridge.js
 *
 * Env vars:
 *   BRIDGE_PORT    — HTTP listen port (default 38406)
 *   PM_URL         — port manager URL (default http://127.0.0.1:38400)
 *   LLM_BASE_URL, LLM_API_KEY, LLM_MODEL_NAME (optional)
 */

import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { request } from 'node:http'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createInterface } from 'node:readline'
import { randomUUID } from 'node:crypto'

const __dirname = dirname(fileURLToPath(import.meta.url))
const MCP_SERVER = resolve(__dirname, 'mcp', 'index.js')
const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || '38406')
const PM_URL = process.env.PM_URL || 'http://127.0.0.1:38400'
const PM_HOST = new URL(PM_URL).hostname
const PM_PORT = parseInt(new URL(PM_URL).port || '38400')
const MCP_START_TIMEOUT = 60_000
const TOOL_TIMEOUT = 120_000
const HEARTBEAT_INTERVAL_MS = 15_000

const SESSION_ID = `bridge_${randomUUID().slice(0, 8)}`

// ---- Port manager client ----

function pmPost(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body)
    const req = request({
      hostname: PM_HOST, port: PM_PORT, path, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString())) }
        catch { reject(new Error('Invalid PM response')) }
      })
    })
    req.on('error', reject)
    req.write(data)
    req.end()
  })
}

async function allocatePort() {
  const result = await pmPost('/allocate', { sessionId: SESSION_ID, pid: process.pid })
  if (result.allocated) return result
  if (result.queued) {
    console.error(`[bridge] All ports busy, waiting in queue (position ${result.position})...`)
    const pollResult = await pmPost('/poll', { sessionId: SESSION_ID, pid: process.pid, timeoutMs: 300000 })
    if (pollResult.allocated) return pollResult
    throw new Error('Queue wait failed')
  }
  throw new Error('Port allocation failed')
}

async function releasePort(leaseId) {
  try { await pmPost('/release', { leaseId }) } catch {}
}

// ---- Heartbeat ----

let heartbeatTimer = null
let currentLeaseId = null

function startHeartbeat(leaseId) {
  currentLeaseId = leaseId
  if (heartbeatTimer) clearInterval(heartbeatTimer)
  heartbeatTimer = setInterval(async () => {
    try { await pmPost('/heartbeat', { leaseId: currentLeaseId }) } catch {}
  }, HEARTBEAT_INTERVAL_MS)
}

function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
}

// ---- MCP child process management ----

let child = null
let rl = null
let initialized = false
let requestId = 0
/** @type {Map<number, {resolve:Function, reject:Function, timer:ReturnType<typeof setTimeout>}>} */
const pendingMap = new Map()

function startMcp(mcpPort) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, PORT: String(mcpPort) }

    child = spawn('node', [MCP_SERVER], {
      env, stdio: ['pipe', 'pipe', 'pipe'],
      cwd: __dirname,
    })

    child.stderr.on('data', (d) => process.stderr.write(`[mcp] ${d}`))

    const startTimer = setTimeout(() => {
      reject(new Error('MCP server start timed out'))
    }, MCP_START_TIMEOUT)

    rl = createInterface({ input: child.stdout })
    let initDone = false

    rl.on('line', (line) => {
      let msg
      try { msg = JSON.parse(line) } catch { return }

      if (!initDone) {
        if (msg.id === 0 && msg.result) {
          initDone = true
          clearTimeout(startTimer)
          initialized = true
          sendMcp({ jsonrpc: '2.0', method: 'notifications/initialized' })
          pollHubConnection().then(resolve).catch(reject)
          return
        }
      }

      // Handle tool call responses (concurrent, matched by id)
      const p = pendingMap.get(msg.id)
      if (p) {
        pendingMap.delete(msg.id)
        clearTimeout(p.timer)
        if (msg.error) {
          p.reject(new Error(msg.error.message || 'Unknown MCP error'))
        } else {
          const content = msg.result?.content
          if (content && Array.isArray(content)) {
            const texts = content.filter(c => c.type === 'text').map(c => c.text).join('\n')
            p.resolve(texts)
          } else {
            p.resolve(JSON.stringify(msg.result))
          }
        }
      }
    })

    child.on('error', (err) => { clearTimeout(startTimer); initialized = false; reject(err) })
    child.on('exit', () => { initialized = false; if (rl) rl.close() })

    sendMcp({
      jsonrpc: '2.0', id: 0, method: 'initialize',
      params: {
        protocolVersion: '2024-11-05',
        capabilities: {},
        clientInfo: { name: 'deepseek-tui', version: '2.0' },
      },
    })
  })
}

function sendMcp(msg) {
  if (!child || child.killed) return
  child.stdin.write(JSON.stringify(msg) + '\n')
}

/**
 * Poll hub connection with exponential backoff.
 * Handles extension reload: when Chrome reloads the extension, hub tabs are
 * recreated by onInstalled and the bridge transparently reconnects.
 *
 * Backoff schedule: 1s → 2s → 4s → 8s → 15s (max), up to 120s total.
 */
async function pollHubConnection() {
  // Fast initial poll: the hub is usually already connected.
  // Backoff: 50ms -> 100ms -> 200ms -> 400ms -> 800ms -> 1.5s -> 3s -> 6s -> 12s (max)
  const maxTotalMs = 60_000
  const maxBackoffMs = 12_000
  const start = Date.now()
  let delay = 50

  while (Date.now() - start < maxTotalMs) {
    try {
      const result = await callMcpTool('get_status', {})
      const status = JSON.parse(result)
      if (status.connected) {
        console.error('[bridge] Hub connected')
        return
      }
    } catch {
      // callMcpTool may fail during MCP re-initialization
    }
    await sleep(delay)
    delay = Math.min(delay * 2, maxBackoffMs)
  }
  throw new Error(`Hub did not connect within ${maxTotalMs / 1000}s. Is the extension loaded?`)
}

function callMcpTool(name, args = {}) {
  return new Promise((resolve, reject) => {
    if (!initialized) return reject(new Error('MCP server not initialized'))

    requestId++
    const id = requestId
    const timer = setTimeout(() => {
      pendingMap.delete(id)
      reject(new Error(`Tool '${name}' timed out after ${TOOL_TIMEOUT/1000}s`))
    }, TOOL_TIMEOUT)

    pendingMap.set(id, { resolve, reject, timer })
    sendMcp({ jsonrpc: '2.0', id, method: 'tools/call', params: { name, arguments: args } })
  })
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }

// ---- HTTP server ----

function jsonResponse(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(data))
}

async function readBody(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(chunk)
  return Buffer.concat(chunks).toString('utf-8')
}

const httpServer = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://localhost:${BRIDGE_PORT}`)
  const path = url.pathname

  try {
    if (path === '/health') {
      jsonResponse(res, 200, { ok: true, initialized, port: BRIDGE_PORT, mcpPort: allocatedPort })
      return
    }

    if (path === '/execute' && req.method === 'POST') {
      const body = await readBody(req)
      let params
      try { params = JSON.parse(body) } catch { return jsonResponse(res, 400, { error: 'Invalid JSON body' }) }
      const { tool, args } = params
      if (!tool) return jsonResponse(res, 400, { error: 'Missing "tool" field' })
      console.error(`[bridge] Executing: ${tool}`)
      const result = await callMcpTool(tool, args || {})
      console.error(`[bridge] Done: ${tool}`)
      jsonResponse(res, 200, { success: true, data: result })
      return
    }

    if (path === '/stop' && req.method === 'POST') {
      try { await callMcpTool('stop_task', {}) } catch {}
      jsonResponse(res, 200, { success: true })
      return
    }

    jsonResponse(res, 404, { error: 'Not found' })
  } catch (err) {
    console.error(`[bridge] Error: ${err.message}`)
    jsonResponse(res, 500, { error: err.message })
  }
})

// ---- Main ----

let allocatedPort = null

async function main() {
  const allocation = await allocatePort()
  allocatedPort = allocation.port
  const leaseId = allocation.leaseId

  console.error(`[bridge] Allocated port ${allocatedPort} (lease ${leaseId.slice(0, 8)})`)

  startHeartbeat(leaseId)

  console.error(`[bridge] Starting MCP server on port ${allocatedPort}...`)
  await startMcp(allocatedPort)
  console.error('[bridge] MCP server ready, hub connected.')

  httpServer.listen(BRIDGE_PORT, '127.0.0.1', () => {
    console.error(`[bridge] HTTP API listening on http://127.0.0.1:${BRIDGE_PORT}`)
  })
}

main().catch((err) => {
  console.error(`[bridge] Failed to start: ${err.message}`)
  process.exit(1)
})

// Cleanup
async function cleanup() {
  stopHeartbeat()
  if (currentLeaseId) {
    await releasePort(currentLeaseId)
    console.error('[bridge] Port released')
  }
  if (rl) rl.close()
  for (const p of pendingMap.values()) { clearTimeout(p.timer); p.reject(new Error('Bridge shutting down')) }
  pendingMap.clear()
  if (child && !child.killed) child.kill()
  httpServer.close()
}

process.on('SIGINT', async () => {
  console.error('[bridge] Shutting down...')
  await cleanup()
  process.exit(0)
})
