/**
 * 指纹去重单测 —— 从 heart.js 里抠真身函数跑，保证测的就是生产代码。
 *
 * 用法：node _test-fp.js
 *
 * 覆盖 5 种投递场景（都是 2026-11-24 实测踩过的）：
 *   1. 同一条 message 跨分钟重播 3 次 → 应只算 1 条（否则白烧 3 次唤醒）
 *   2. talk 句数真变了 3句→4句     → 应算 2 条（正文变了就是新内容）
 *   3. 同一班两次来活、正文相同     → 应算 2 条（漏一件扣 6 贝）
 *   4. 同一条 work 同分钟重播       → 应算 1 条
 *   5. 两个人同一分钟各说一句       → 应算 2 条
 */
const fs = require('node:fs')

const src = fs.readFileSync(__dirname + '/heart.js', 'utf8')

function grab(name) {
  const i = src.indexOf('function ' + name + '(')
  if (i < 0) throw new Error('找不到 ' + name)
  let d = 0, j = src.indexOf('{', i)
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') d++
    else if (src[k] === '}') { d--; if (d === 0) return src.slice(i, k + 1) }
  }
  throw new Error('括号不配 ' + name)
}

// 顺序有依赖：fingerprintOf 调 stampOf / speakerOf
const code = [grab('fnv1a'), grab('stampOf'), grab('speakerOf'), grab('fingerprintOf')].join('\n')
  + '\nmodule.exports={fingerprintOf}'
const mod = { exports: {} }
new Function('module', 'exports', 'require', code)(mod, mod.exports, require)
const { fingerprintOf } = mod.exports

const cases = [
  ['同一条 message 被跨分钟重播 3 次', [
    { kind: 'message', from: '小鱼#1234', text: '小鱼#1234给你发了一条消息', time: '19:22' },
    { kind: 'message', from: '小鱼#1234', text: '小鱼#1234给你发了一条消息', time: '19:24' },
    { kind: 'message', from: '小鱼#1234', text: '小鱼#1234给你发了一条消息', time: '19:33' },
  ], 1],
  ['talk 句数真变了（3句→4句）', [
    { kind: 'talk', from: '小鱼#1234', text: '小鱼#1234当面对你说了3句话', time: '18:35' },
    { kind: 'talk', from: '小鱼#1234', text: '小鱼#1234当面对你说了4句话', time: '18:36' },
  ], 2],
  ['同一班两次来活（正文相同、分钟不同）', [
    { kind: 'work', text: '小票机卡了一张纸', time: '19:10' },
    { kind: 'work', text: '小票机卡了一张纸', time: '19:30' },
  ], 2],
  ['同一条 work 重播（同分钟）', [
    { kind: 'work', text: '小票机卡了一张纸', time: '19:10' },
    { kind: 'work', text: '小票机卡了一张纸', time: '19:10' },
  ], 1],
  ['两个人同一分钟各说一句', [
    { kind: 'talk', from: '小鱼#1234', text: '小鱼#1234当面对你说了2句话', time: '21:00' },
    { kind: 'talk', from: '米米#1234', text: '米米#1234当面对你说了2句话', time: '21:00' },
  ], 2],
]

let bad = 0
for (const [name, items, want] of cases) {
  const got = new Set(items.map(fingerprintOf)).size
  const ok = got === want
  if (!ok) bad++
  console.log((ok ? '✅' : '❌') + ' ' + name + '：' + got + ' 条（应 ' + want + '）')
}
console.log(bad === 0 ? '\n全部通过' : '\n' + bad + ' 条不通过')
process.exit(bad === 0 ? 0 : 1)