/**
 * 自己的会话名自解析（不写死，改名后自动跟上）
 *
 * 原理：reason-network 的 network.db 里 sessions 表主键就是 `<agent>:<session-id>`，
 * 而 ZCode 会话的环境变量 ZCODE_SESSION_ID 正是那个 session-id。
 * 所以查询  key = 'zcode:' + $ZCODE_SESSION_ID  →  sessions.name
 *
 * 实测（2026-11-24 20:56）：
 *   ZCODE_SESSION_ID = sess_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
 *   → sessions.key  = zcode:sess_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
 *   → sessions.name = example-session
 *
 * 为什么不用 `reason-network who` 解析：它输出的是给人看的表格，
 * 「← you」这行不稳（实测有刷新延迟时压根不出现），不适合脚本。
 *
 * 用法：
 *   const { resolveSelf } = require('./resolve-self')
 *   const me = resolveSelf()          // → 'yestar/example-session' 或 null
 */
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const DB = path.join(process.env.USERPROFILE || '.', '.reason', 'network', 'network.db')

/**
 * @returns {{person: string, name: string, address: string, doing: string}|null}
 */
function resolveSelf() {
  const sid = process.env.ZCODE_SESSION_ID || process.env.CLAUDE_CODE_SESSION_ID
  if (!sid) return null

  const person = process.env.REASON_NETWORK_PERSON || 'yestar'
  const key = 'zcode:' + sid

  // sqlite3 CLI 不一定在 PATH；直接用 node 自带的 node:sqlite（Node 22+）
  let DatabaseSync
  try {
    ;({ DatabaseSync } = require('node:sqlite'))
  } catch {
    return null
  }

  let db
  try {
    db = new DatabaseSync(DB, { readOnly: true })
    const row = db.prepare('SELECT name, agent, doing FROM sessions WHERE key = ?').get(key)
    if (!row) return null
    return { person, name: row.name, address: person + '/' + row.name, doing: row.doing || '' }
  } catch {
    return null
  } finally {
    try { db && db.close() } catch {}
  }
}

module.exports = { resolveSelf, DB }

if (require.main === module) {
  const me = resolveSelf()
  if (!me) {
    console.log('解析失败：ZCODE_SESSION_ID=' + (process.env.ZCODE_SESSION_ID || '(空)'))
    process.exit(1)
  }
  console.log('address =', me.address)
  console.log('doing   =', me.doing || '(空)')
}