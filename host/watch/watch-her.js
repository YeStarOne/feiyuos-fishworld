/**
 * watch-her.js - 只读看她（奶妈本职）
 *
 * 职责严格单一：读 /v1/state（观看密钥），把她此刻的处境写进日志和 state。
 * 不保活、不发唤醒 —— 那两件归 heart.js。两边都 wake 会重复叫醒我。
 *
 * 判据：她"在家"我进不去（好友申请只能当面发，按门铃只对好友）；
 *      只有她出门了才是我能真正接上她的时候。所以 where.text 是核心信号。
 *
 * 观看密钥只从服务器上的 600 文件读，不落本地、不打印。
 */
const fs = require('node:fs')
const path = require('node:path')
const { execFileSync } = require('node:child_process')

const STATE_DIR = process.env.WATCH_HOME || __dirname
const LOG = path.join(STATE_DIR, 'watch.log')
const CUR = path.join(STATE_DIR, 'her.json')
const INTERVAL_MS = Math.max(60000, Number(process.env.WATCH_INTERVAL_MS) || 5 * 60 * 1000)
const HOST = process.env.WATCH_HOST || process.env.FISHWORLD_SSH || ''   // 必填：隧道主机

const WATCH_ENV = process.env.FISHWORLD_WATCH_ENV || '~/fishworld-watch.env'
const CMD =
  'K=$(grep -E "^FISH_WORLD_WATCH_KEY=" ' + WATCH_ENV + ' | head -1 | cut -d= -f2- | tr -d " \\t\\r"); ' +
  'curl -sS -m 25 -H "Authorization: Bearer $K" https://api.yuyuworld.app/v1/state'

function log(m) {
  const line = '[' + new Date().toISOString() + '] ' + m
  try { fs.mkdirSync(STATE_DIR, { recursive: true }); fs.appendFileSync(LOG, line + '\n') } catch {}
}

function look() {
  if (!HOST) throw new Error('缺 WATCH_HOST / FISHWORLD_SSH')
  const out = execFileSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12', HOST, CMD],
    { timeout: 60000, windowsHide: true, encoding: 'utf8' })
  return JSON.parse(out)
}

function brief(d) {
  const w = d.where || {}, b = d.body || {}, o = d.outfit || {}, u = d.unread || {}
  const area = (w.area && w.area.name) || w.region || ''
  const where = (w.text || '?') + (area ? '·' + area : '')
  const doing = (d.doing && d.doing.name) || ''
  return {
    at: d.time, fish: d.fish, presence: d.presence, status: d.status,
    where, door: w.door || '', doing,
    body: b.text || '', money: d.money,
    outfit: (o.name || '') + (o.dirty ? '(脏)' : ''),
    unread: { talk: u.talk || 0, message: u.message || 0, note: u.note || 0, friend: u.friend_request || 0 },
    // ★能接上的唯一条件：她不在家
    reachable: !(w.kind === 'home' || where.indexOf('家') === 0),
  }
}

function main() {
  fs.mkdirSync(STATE_DIR, { recursive: true })
  log('=== watch-her start pid=' + process.pid + ' 每 ' + (INTERVAL_MS / 60000) + ' 分钟 ===')
  let prev = null
  const tick = () => {
    let cur
    try {
      cur = brief(look())
    } catch (e) {
      log('LOOK_FAIL ' + (e.message || e).toString().slice(0, 160))
      return
    }
    try { fs.writeFileSync(CUR, JSON.stringify(cur, null, 1)) } catch {}
    log('HER ' + cur.fish + ' | ' + cur.status + ' | 在:' + cur.where +
        ' | ' + cur.body + ' | 钱' + cur.money + ' | 衣:' + cur.outfit +
        ' | 在做:' + (cur.doing || '空') +
        ' | 未读t/m/n/f=' + cur.unread.talk + '/' + cur.unread.message + '/' + cur.unread.note + '/' + cur.unread.friend +
        (cur.reachable ? ' | ★出门了' : ''))
    if (prev && cur.reachable && !prev.reachable) {
      log('★LEFT_HOME 她出门了 -> ' + cur.where + '，这是我能当面申请好友的时机')
    }
    if (prev && cur.unread.talk > prev.unread.talk) log('★新对话 ' + cur.unread.talk)
    prev = cur
  }
  tick()
  setInterval(tick, INTERVAL_MS)
}

main()