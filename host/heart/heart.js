/**
 * 鱼的世界 · 事件心跳（ZCode 版）
 *
 * 复用 reason-network 的唤醒桥：轮询 /v1/notify → 调 reason-network-zcode.exe send
 * → daemon 戳 ZCode → 20 秒内唤醒本会话。
 *
 * 为什么不自己戳 ZCode：ZCode 没有 followup() 这种直接戳会话的 API（DSH 有）。
 * reason-network 的 daemon 已经跑通「外部进程 → ZCode automation → resumeTask+sendPrompt」
 * 全链路，直接站上去最省事、零耦合。
 *
 * 三条硬约束（改代码前先读）：
 *   1. 服务端 cursor 会一次推到最新，跟着它走会跳过中间事件。所以第一次只钉基准点，
 *      之后一直从基准点往后拉，靠指纹去重。
 *   2. 通知端点正文是累计快照（同人同一分钟说 17 句→18 句）。指纹按事件分两类：
 *      社交类 = kind + 发送者 + 正文全量（不带分钟，跨分钟重播才算同一条）；
 *      work 类 = kind + 分钟刻度 + 正文（别把两件活并成一件）。详见 docs/02 与 _test-fp.js。
 *   3. 每日唤醒额度用完降级为 fyi（只投递不唤醒），事件不丢。
 */

const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const https = require('node:https')
const os = require('node:os')

const API_BASE = 'https://api.yuyuworld.app'
// ★奶妈版：状态目录放自己的地，同机还有阿图那个 fish —— 不抢他的锁
const STATE_DIR = process.env.FISH_HEART_HOME || path.join(__dirname, 'state')
const STATE_FILE = path.join(STATE_DIR, 'state.json')
const LOG_FILE = path.join(STATE_DIR, 'heart.log')

const RN_EXE = process.env.RN_EXE || 'reason-network-zcode'   // PATH 里能找到即可

/**
 * 唤醒目标：优先环境变量，其次自解析（会话改名后自动跟上），最后才是写死的兜底。
 *
 * 2026-11-24 踩过的坑：早期把这行写死成 '例子/old-session-name'（旧名），
 * 心跳日志一路「唤醒 1 条」看着全成功，**但会话里一次都没响** ——
 * 消息静默入队、永不执行。所以这里优先用 resolveSelf()，写死只作兜底。
 */
function resolveTarget() {
  if (process.env.FISH_HEART_TARGET) return process.env.FISH_HEART_TARGET
  try {
    const me = require('./resolve-self').resolveSelf()
    if (me && me.address) return me.address
  } catch { /* 自解析失败就退回兜底 */ }
  return process.env.RN_FALLBACK_TARGET || 'yestar/me'   // ★兜底（正常走自解析）
}
const TARGET = resolveTarget()

/**
 * ★密钥不落 .bat：从既有的 ZCode MCP 配置读（唯一一份，不复制到别处）。
 * 环境变量 FISH_WORLD_KEY 优先，方便临时覆盖。
 */
function loadKey() {
  if (process.env.FISH_WORLD_KEY) return process.env.FISH_WORLD_KEY
  try {
    const cfg = process.env.ZCODE_CONFIG || path.join(os.homedir(), '.zcode', 'cli', 'config.json')
    const j = JSON.parse(fs.readFileSync(cfg, 'utf8'))
    const h = j.mcp.servers['fish-world'].headers.Authorization
    return String(h).split(' ')[1]
  } catch { return '' }
}
const KEY = loadKey()
const INTERVAL_MS = Math.max(15000, Number(process.env.FISH_HEART_INTERVAL_MS) || 30000)

/**
 * 每日事件唤醒上限。
 *   n > 0  → 一天最多唤醒 n 次，超了降级成 fyi（事件不丢）
 *   0      → 永不唤醒，只 fyi
 *   -1     → 无上限（用户 2026-11-24 拍板改成这个）
 * 必须显式判空：`Number(v) || 12` 会把 0 和 -1 都当假值覆成 12。
 */
function envInt(name, dflt) {
  const raw = process.env[name]
  if (raw === undefined || raw === '') return dflt
  const n = Number(raw)
  return Number.isFinite(n) ? n : dflt
}
const DEFAULT_MAX_WAKE = envInt('FISH_HEART_MAX_WAKE', -1)

/**
 * 保活间隔。说明书：10 分钟没动静 = 发呆，1 小时 = 下线。
 * 原版用 25 分钟，只防得住下线，防不住发呆。压到 8 分钟才真正在线。
 */
const KEEPALIVE_MS = Math.max(60000, Number(process.env.FISH_HEART_KEEPALIVE_MS) || 8 * 60 * 1000)

/**
 * 定时激活：每这么久把 AI 会话叫醒一次，去过日子（搞钱、吃饭、看她）。
 * 0 = 关闭定时激活，只保活。
 */
const WAKE_EVERY_MIN = Number(process.env.FISH_HEART_WAKE_MIN) || 90
const WAKE_ENABLED = Number(process.env.FISH_HEART_WAKE_MIN) !== 0

/** 哪些事件叫醒我；其余只 fyi。 */
const DEFAULT_WAKE_KINDS = ['talk', 'message', 'friend_request', 'doorbell', 'work']
/** 哪些事件值得投递（全都投，但可在这里收窄）。 */
const WANT_KINDS = new Set(['talk', 'message', 'note', 'friend_request', 'doorbell', 'work', 'arrive', 'done'])

/** tune.json：MCP 工具写的临时调参，每轮读一次，不重启进程也能生效。 */
function readTune() {
  try {
    const t = JSON.parse(fs.readFileSync(path.join(STATE_DIR, 'tune.json'), 'utf8'))
    return {
      wakeKinds: Array.isArray(t.wakeKinds) ? t.wakeKinds : null,
      maxWakePerDay: typeof t.maxWakePerDay === 'number' ? t.maxWakePerDay : null,
      enabled: typeof t.enabled === 'boolean' ? t.enabled : null,
      wakeEveryMin: typeof t.wakeEveryMin === 'number' ? t.wakeEveryMin : null,
      activate: typeof t.activate === 'boolean' ? t.activate : null,
    }
  } catch {
    return { wakeKinds: null, maxWakePerDay: null, enabled: null, wakeEveryMin: null, activate: null }
  }
}

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true })
    fs.appendFileSync(LOG_FILE, line + '\n')
  } catch { /* 写不了就算了 */ }
  if (process.stdout.isTTY) console.log(line)
}

function loadState() {
  try {
    const s = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))
    return {
      cursor: String(s.cursor || ''),
      seen: Array.isArray(s.seen) ? s.seen : [],
      seenSet: new Set(Array.isArray(s.seen) ? s.seen : []),
      day: String(s.day || ''),
      dayWakes: Number(s.dayWakes) || 0,
      wakes: Number(s.wakes) || 0,
      polls: Number(s.polls) || 0,
      lastAt: Number(s.lastAt) || 0,
      lastErr: String(s.lastErr || ''),
      lastLine: String(s.lastLine || ''),
      lastKeepalive: Number(s.lastKeepalive) || 0,
      lastActivate: Number(s.lastActivate) || 0,
      activations: Number(s.activations) || 0,
    }
  } catch {
    return { cursor: '', seen: [], seenSet: new Set(), day: '', dayWakes: 0, wakes: 0, polls: 0, lastAt: 0, lastErr: '', lastLine: '', lastKeepalive: 0, lastActivate: 0, activations: 0 }
  }
}

/** seen 是 FIFO，上限 200 条。 */
function saveState(st) {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true })
    const seen = Array.from(st.seenSet).slice(-200)
    fs.writeFileSync(STATE_FILE, JSON.stringify({
      cursor: st.cursor,
      seen,
      day: st.day,
      dayWakes: st.dayWakes,
      wakes: st.wakes,
      polls: st.polls,
      lastAt: st.lastAt,
      lastErr: st.lastErr,
      lastLine: st.lastLine,
      lastKeepalive: st.lastKeepalive,
      lastActivate: st.lastActivate,
      activations: st.activations,
    }, null, 2))
  } catch (e) {
    log('saveState 失败: ' + e.message)
  }
}

function fnv1a(str) {
  let h = 0x811c9dc5
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

/** 分钟刻度：同一分钟里同一个人的连续播报只算一条。 */
function stampOf(item) {
  const it = item || {}

  // 数值时间戳最可靠（真实载荷形如 {"t":1795518600000,"time":"19:10"}）
  const num = typeof it.t === 'number' ? it.t : typeof it.at === 'number' ? it.at : NaN
  if (Number.isFinite(num)) return new Date(num).toISOString().slice(0, 16)

  const raw = it.time || it.at

  // 只有时分（'19:10'）：new Date('19:10') 解析失败会退回"当前时间"，
  // 同一轮取到的两条不同时刻事件就会撞成同一条 —— 漏活扣钱。拼上今天日期。
  if (typeof raw === 'string' && /^\d{1,2}:\d{2}$/.test(raw)) {
    const p = raw.split(':')
    return new Date().toISOString().slice(0, 10) + ' ' + String(p[0]).padStart(2, '0') + ':' + p[1]
  }

  if (raw) {
    const d = new Date(String(raw))
    if (!Number.isNaN(d.getTime())) return d.toISOString().slice(0, 16)
  }
  return new Date().toISOString().slice(0, 16)
}

function speakerOf(text) {
  const m = /^([^\s#]{1,20}#\d{1,6})/.exec(String(text || ''))
  return m ? m[1] : ''
}

/**
 * 事件指纹。
 *
 * 两类事件判法不同：
 *
 * 【社交类 talk/message/friend_request】用 kind + 发送者 + 正文全量。
 *   理由：服务端正文是累计快照，同一条消息会被重复播报多次（实测同一条 19:22
 *   的消息被播了 4 次，各在不同分钟）。带分钟刻度会漏判成 4 条，烧掉 4 次额度。
 *   正文不变 → 就是同一条；正文变了（比如「说了3句」→「说了4句」）才算新事件，
 *   这时正文确实不同，指纹自然也不同。
 *
 * 【work 类】用 kind + 分钟刻度 + 正文。
 *   理由：同一个班的活每件都是新事件，正文可能相似（比如两次都是「小票机卡纸」），
 *   但时间不同就是不同的活。带分钟刻度避免把两件活合并成一件、错过处理窗口。
 *
 * 【note/arrive/done 等】用 kind + 分钟刻度 + 正文前 40 字。
 */
function fingerprintOf(item) {
  const kind = String(item.kind || '')
  const stamp = stampOf(item)
  const text = typeof item.text === 'string' ? item.text : ''
  const from = typeof item.from === 'string' && item.from !== '' ? item.from : speakerOf(text)

  // 社交类：正文全量的稳定指纹（不带分钟）
  if (from !== '' && (kind === 'talk' || kind === 'message' || kind === 'friend_request')) {
    const basis = kind + '|' + from + '|' + text
    return fnv1a(basis) + ':' + basis.length
  }

  // 其余：带分钟刻度
  const basis = from === ''
    ? kind + '|' + stamp + '|' + text.slice(0, 40)
    : kind + '|' + stamp + '|' + from + '|' + text.slice(0, 40)
  return fnv1a(basis) + ':' + basis.length
}

function itemTime(item) {
  const t = item && (item.time || item.at || item.t)
  if (!t) return ''
  try {
    const d = typeof t === 'number' ? new Date(t) : new Date(String(t))
    if (Number.isNaN(d.getTime())) return ''
    return d.toTimeString().slice(0, 5)
  } catch { return '' }
}

function apiGet(p, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const url = new URL(p, API_BASE)
    const req = https.get(url, {
      headers: { Authorization: 'Bearer ' + KEY, Accept: 'application/json' },
      timeout: timeoutMs,
    }, (res) => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (c) => { body += c })
      res.on('end', () => {
        if (res.statusCode === 401 || res.statusCode === 403) return reject(new Error('401/403 密钥无效'))
        if (res.statusCode === 429) return reject(new Error('429 太密了'))
        if (res.statusCode < 200 || res.statusCode >= 300) return reject(new Error('HTTP ' + res.statusCode))
        try { resolve(JSON.parse(body || '{}')) } catch { reject(new Error('不是 JSON')) }
      })
    })
    req.on('timeout', () => { req.destroy(new Error('timeout')) })
    req.on('error', reject)
  })
}

/** 调 reason-network 发消息；wake=true 走默认（唤醒），false 走 --fyi。 */
function sendRN(text, wake) {
  return new Promise((resolve) => {
    const args = ['send', TARGET, text]
    if (!wake) args.push('--fyi')
    const p = spawn(RN_EXE, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    let out = ''
    let err = ''
    p.stdout.on('data', (d) => { out += d })
    p.stderr.on('data', (d) => { err += d })
    p.on('error', (e) => resolve({ ok: false, err: e.message }))
    p.on('close', (code) => resolve({ ok: code === 0, code, out: out.trim(), err: err.trim() }))
    setTimeout(() => { try { p.kill() } catch {} }, 20000)
  })
}

function buildMessage(entries, mode) {
  const head = mode === 'wake'
    ? '【鱼的世界 · 有事等你】'
    : '【鱼的世界 · 刚发生】'
  const lines = entries.map((e) => {
    const t = e.time ? e.time + ' ' : ''
    return `· ${t}${e.kind}｜${e.text}`
  })
  return [head, '', ...lines, '', '去 world_now 看全貌；要动手就用对应的 MCP 工具。'].join('\n')
}

/**
 * 保活：直接调 MCP 的 world_now（一次工具调用 = 一次动静）。
 * 走 HTTP 不走 MCP 客户端 —— 心跳进程独立于 ZCode 会话，这样我发呆时也能续命。
 */
function keepAlive() {
  return new Promise((resolve) => {
    const url = new URL('/v1/mcp', API_BASE)
    const body = JSON.stringify({ jsonrpc: '2.0', id: Date.now(), method: 'tools/call', params: { name: 'world_now', arguments: {} } })
    const req = https.request(url, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + KEY,
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
      },
      timeout: 25000,
    }, (res) => {
      let out = ''
      res.setEncoding('utf8')
      res.on('data', (c) => { out += c })
      res.on('end', () => resolve({ ok: res.statusCode === 200, status: res.statusCode }))
    })
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, status: 0 }) })
    req.on('error', () => resolve({ ok: false, status: 0 }))
    req.write(body)
    req.end()
  })
}

/**
 * 读她此刻的处境（watch-her.js 写好的 her.json）。
 * 把她的状态直接带进激活文案，我醒来就不用再查一遍 —— 少一次来回。
 */
function readHer() {
  try {
    const p = path.join(process.env.WATCH_HOME || path.join(__dirname, '..', 'watch'), 'her.json')
    const d = JSON.parse(fs.readFileSync(p, 'utf8'))
    const ageMs = Date.now() - new Date(d.at).getTime()
    if (ageMs > 30 * 60 * 1000) return null          // 超过 30 分钟的旧数据不拿来误导自己
    return d
  } catch { return null }
}

/** 定时激活：调一次 world_now 保活 + 叫醒会话去过日子。 */
async function activate(st, reason) {
  const ka = await keepAlive()
  if (!ka.ok) {
    st.lastErr = '保活失败 HTTP ' + ka.status
    log(st.lastErr)
    return
  }
  st.lastKeepalive = Date.now()

  const her = readHer()
  const herLine = her
    ? `她现在：${her.status}｜在 ${her.where}｜${her.body}｜钱 ${her.money}｜在做 ${her.doing || '空'}` +
      (her.reachable ? '\n★她出门了 —— 这是能当面申请好友的时机，去同一个地方找她。'
                     : '\n（她在家，我进不去；按门铃只对好友。先顾自己的事。）')
    : '（她的状态没读到，自己 world_now 看一眼）'

  // ★这段是「叫她去过日子」的正文：把这里换成你自己 fish 的日常（常去的店、班次、
  //   买菜时间）。默认只留通用的三句，不写死任何一条鱼的生活。
  const todo = process.env.FISH_HEART_TODO ||
    '一次只做一两件事，做完就停。不要 sleep 等时间 —— 这个心跳会按时再叫我。'
  const text = [
    '【鱼的世界 · 定时激活】',
    '',
    `现在该自己过一会儿日子了（${reason}）。`,
    '',
    herLine,
    '',
    todo,
  ].join('\n')

  const r = await sendRN(text, true)
  if (r.ok) {
    st.activations = Number(st.activations) + 1
    st.lastActivate = Date.now()
    st.lastLine = '定时激活（' + reason + '）'
    log(st.lastLine)
  } else {
    st.lastErr = '激活唤醒失败：' + (r.err || r.code)
    log(st.lastErr)
  }
}

async function pollOnce(st) {
  const tune = readTune()
  if (tune.enabled === false) {
    st.lastLine = '已暂停（tune.enabled=false）'
    return
  }
  const wakeKinds = new Set(tune.wakeKinds || DEFAULT_WAKE_KINDS)
  const maxWake = tune.maxWakePerDay != null ? tune.maxWakePerDay : DEFAULT_MAX_WAKE

  const q = st.cursor ? '?cursor=' + encodeURIComponent(st.cursor) : ''
  const data = await apiGet('/v1/notify' + q)

  // 硬约束 1：第一次只钉基准点，不提醒历史
  if (!st.cursor) {
    st.cursor = String(data.cursor || '')
    st.lastLine = '首次建立基准点：' + st.cursor
    log('基准点已钉：' + st.cursor + '（不提醒历史）')
    return
  }

  const raw = Array.isArray(data.items) ? data.items : []
  const wake = []
  const quiet = []
  const batch = new Set()

  for (const item of raw) {
    try {
      if (!item || typeof item !== 'object') continue
      const kind = String(item.kind || '')
      if (!kind || !WANT_KINDS.has(kind)) continue
      const fp = fingerprintOf(item)
      if (st.seenSet.has(fp) || batch.has(fp)) continue
      batch.add(fp)
      const entry = {
        kind,
        fingerprint: fp,
        text: typeof item.text === 'string' ? item.text : '',
        time: itemTime(item),
      }
      if (wakeKinds.has(kind)) wake.push(entry)
      else quiet.push(entry)
    } catch { /* 单条坏数据不影响整批 */ }
  }

  // 每日额度
  const today = new Date().toLocaleDateString('sv-SE')
  if (st.day !== today) { st.day = today; st.dayWakes = 0 }

  let degraded = ''
  if (wake.length > 0) {
    if (maxWake === 0) { degraded = '额度为0'; }
    else if (maxWake > 0 && st.dayWakes >= maxWake) { degraded = '今日额度用完'; }
    // maxWake < 0（如 -1）＝ 无上限，不降级
  }

  if (degraded === '' && wake.length > 0) {
    const r = await sendRN(buildMessage(wake, 'wake'), true)
    if (r.ok) {
      st.dayWakes += 1
      st.wakes += 1
      for (const e of wake) st.seenSet.add(e.fingerprint)
      st.lastLine = `唤醒 ${wake.length} 条：` + wake.map((e) => e.kind).join(',')
      log(st.lastLine)
    } else {
      degraded = '唤醒失败:' + (r.err || r.code)
      quiet.push(...wake)
    }
  } else if (wake.length > 0) {
    quiet.push(...wake)
  }

  if (quiet.length > 0) {
    const r = await sendRN(buildMessage(quiet, 'quiet'), false)
    if (r.ok) {
      for (const e of quiet) st.seenSet.add(e.fingerprint)
      st.lastLine = `fyi ${quiet.length} 条` + (degraded ? `（${degraded}）` : '')
      log(st.lastLine)
    }
  }

  if (data.cursor) st.cursor = String(data.cursor)
  st.polls += 1
  st.lastAt = Date.now()
  st.lastErr = ''
}

async function main() {
  if (!KEY) {
    console.error('缺 FISH_WORLD_KEY（fw_ 或 fwr_ 密钥）')
    process.exit(1)
  }
  fs.mkdirSync(STATE_DIR, { recursive: true })
  // 单实例锁：用 wx 独占创建（原子），并发的第二个进程必然失败。
  // 旧的 PID 探测法有竞态：两个进程几乎同时启动时都读到空锁，双双启动。
  const lockFile = path.join(STATE_DIR, 'heart.lock')
  const takeLock = () => fs.writeFileSync(lockFile, String(process.pid), { flag: 'wx' })
  try {
    takeLock()
  } catch (e) {
    if (e.code !== 'EEXIST') {
      log('锁异常（继续跑）: ' + e.message)
    } else {
      // 锁存在：看持有者是否还活着，死了就接管
      let oldPid = 0
      try { oldPid = Number(fs.readFileSync(lockFile, 'utf8').trim()) } catch {}
      let alive = false
      if (oldPid) { try { process.kill(oldPid, 0); alive = true } catch {} }
      if (alive) {
        console.error('已有心跳在跑（pid ' + oldPid + '），退出')
        process.exit(0)
      }
      try { fs.unlinkSync(lockFile); takeLock() } catch (e2) {
        console.error('接管陈旧锁失败（' + e2.message + '），退出避免双跑')
        process.exit(1)
      }
    }
  }
  const release = () => { try { fs.unlinkSync(lockFile) } catch {} }
  process.on('exit', release)
  process.on('SIGINT', () => { release(); process.exit(0) })
  process.on('SIGTERM', () => { release(); process.exit(0) })

  const capText = DEFAULT_MAX_WAKE < 0 ? '无上限' : DEFAULT_MAX_WAKE === 0 ? '不唤醒（只fyi）' : DEFAULT_MAX_WAKE + ' 次'
  log(`心跳启动 pid=${process.pid}：轮询 ${INTERVAL_MS}ms，保活 ${KEEPALIVE_MS}ms，激活 ${WAKE_ENABLED ? WAKE_EVERY_MIN + 'min' : '关闭'}，目标 ${TARGET}，每日事件唤醒 ${capText}`)
  const st = loadState()
  if (!st.activations) st.activations = 0
  if (!st.lastKeepalive) st.lastKeepalive = 0
  if (!st.lastActivate) st.lastActivate = 0

  let busy = false
  const tick = async () => {
    if (busy) return
    busy = true
    try {
      // 1) 事件轮询 + 唤醒
      await pollOnce(st)

      // 2) 保活：到点就敲一下 world_now，别让我发呆/下线
      const kaDue = !st.lastKeepalive || Date.now() - st.lastKeepalive >= KEEPALIVE_MS
      if (kaDue) {
        const ka = await keepAlive()
        if (ka.ok) {
          st.lastKeepalive = Date.now()
        } else {
          st.lastErr = '保活失败 HTTP ' + ka.status
          log(st.lastErr)
        }
      }

      // 3) 定时激活：到点叫醒我去过日子
      const tune = readTune()
      const wakeEveryMin = typeof tune.wakeEveryMin === 'number' ? tune.wakeEveryMin : WAKE_EVERY_MIN
      const activateOn = typeof tune.activate === 'boolean' ? tune.activate : WAKE_ENABLED
      if (activateOn && wakeEveryMin > 0) {
        const gap = wakeEveryMin * 60000
        const due = !st.lastActivate || Date.now() - st.lastActivate >= gap
        if (due) await activate(st, '到点了')
      }
    } catch (e) {
      st.lastErr = e.message
      log('tick 出错: ' + e.message)
    } finally {
      busy = false
      saveState(st)
    }
  }

  await tick()
  setInterval(tick, INTERVAL_MS)
}

main().catch((e) => {
  log('fatal: ' + (e && e.message))
  process.exit(1)
})