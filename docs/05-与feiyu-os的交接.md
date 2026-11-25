# 05 · 与 feiyu-os 的交接

## 本仓在生态里的位置

[deepseek-superagent-feiyu-os](https://github.com/YeStarOne/deepseek-superagent-feiyu-os)
是我们的开源橱窗 + 主架构仓；它下面分两层：

| 层 | 是什么 | 举例 |
| --- | --- | --- |
| **平台仓**（私有） | 一条数字生命跑起来需要的平台改造：QQ 桥、模型路由、记忆、唤醒插件的配置 | `qq-plugin`、`superagent-sources`、`cordis.patch.yml` |
| **车道仓**（本仓属于这层） | 一个具体世界的接入：把那个世界的事件变成「她被叫醒」，再把她的动作变成世界里的事 | `feiyuos-stardew-ai-farmer`、`feiyuos-starpost-relay`、**`feiyuos-fishworld`** |

一句话分工：**平台仓管「她是谁、怎么说话、怎么记事」；本仓管「她在鱼的世界里怎么被叫醒、
怎么伸手」。**

## 与平台仓的接口（只写接口，不写值）

| 接口 | 位置 | 本仓怎么用 |
| --- | --- | --- |
| ZCode MCP 配置 | `~/.zcode/cli/config.json` 的 `mcp.servers['fish-world']` | `heart.js` / `nanny_beat.py` 从这里取操作密钥（唯一一份，不复制）。密钥本体不进本仓 |
| `fishworld-reminder` 插件 | 平台仓的 `cordis.patch.yml` | 世界事件推送、`idleWake*`（沉默太久也叫人）、`maxNotifiesPerDay`。改法见 `ops/patch-*.py` |
| `dsh-life-slot` 插件 | 同上 | `maxPerDay`（每回合最多注入几条人生片段） |
| `dsh-fish-world` 插件 | 同上 | `maxWakePerDay`（side 看护额度）、side 硬时限告警 |
| Reason Network CLI | `RN_EXE` | 唯一的「叫醒会话」通道：`reason-network-zcode send <地址> <正文> [--fyi]` |
| RN 会话库 | `~/.reason/network/network.db`（只读） | 按 `zcode:<ZCODE_SESSION_ID>` 自解析唤醒目标 |
| ZCode 注入的环境 | `ZCODE_SESSION_ID` / `CLAUDE_CODE_SESSION_ID` | 自解析的输入；不用手工配 |

**引擎侧的一条硬事实**（决定了我们为什么在平台侧补 `idleWake`）：
外部推送（`source=fish-world`）**断不了**会话里正在等的 `wait`——引擎只认 `kind=user`。
所以她在长 `sleep` 里等时间的时候，任何外部唤醒都插不进去。两条对策：
本仓让她**不要 sleep 等时间**（`FISH_HEART_TODO`）；平台侧补「沉默太久也叫人」，
并且靠宿主 QQ 消息（`kind=user`）去断 `wait`。

## 与星露谷那条车道的关系

同一个「奶妈」模式，两个世界：

| | 星露谷（`feiyuos-stardew-ai-farmer`） | 鱼的世界（本仓） |
| --- | --- | --- |
| 世界接口 | 本地 HTTP 桥（7842/7843）+ SMAPI | 远程 HTTPS MCP + REST |
| 叫醒源 | 换日触发器、Bridge 状态、看护器 | `/v1/notify` 事件流 + 定时激活 |
| 伸手方式 | `lib.mjs` 调桥 | `nanny_beat.py` 过 ssh 隧道调 MCP |
| 共同的原则 | 外部进程负责叫；只读看她；不替她做决定；不搬她的身体、体力、睡眠 | 同左 |

两仓不共享代码（一个 node + 桥，一个 python + 隧道），共享的是**形状**：
轮询 → 去重 → 叫醒 → 四层验收。

## 本仓不包含（故意）

- 世界的服务端、协议实现。
- 她的人格、人设、记忆、日记——那是平台仓和另一个仓的事。
- 任何密钥、主机地址、会话名、某只具体鱼的私人数据。代码里的路径全部相对，主机全部 env。
- 平台侧的插件本体（`fishworld-reminder` 等），本仓只放**改它们的补丁脚本**。

## 把这一套接到另一个世界（移植清单）

1. **接口三件套**：一个「拉事件」的接口、一个「调工具」的 JSON-RPC/MCP、一个「只读看她」的接口。
   三者的差别写进 `apiGet` / `rpc` / `act.call` 就够了。
2. **链路**：如果本机出网被代理打坏，加 ssh 隧道（`nanny_beat.tunnel_up` 是现成的）。
3. **唤醒桥**：换成你那边的「外部进程 → 会话」。本仓用 RN；DSH 有 `followup()` 就不用桥。
4. **去重**：先确认事件流是增量还是累计快照。累计快照必须去重，且**按事件类型分两类**
   （社交不带分钟，工作带分钟）——照抄 `fingerprintOf` + 改测试用例。
5. **额度语义**：`0` / `-1` / `n` 三档，显式判空。
6. **定时激活正文**：`FISH_HEART_TODO` 换成那只鱼自己的生活。别写死任何一条鱼。
7. **验收**：四层证据，一层都不能省。

## 交接检查单

- [ ] `FISHWORLD_SSH` 填好，`ssh <host> true` 免密通
- [ ] 操作密钥只有一处来源；`node host/heart/heart.js` 能打印「目标 …」
- [ ] 观看密钥文件在隧道主机上 600，变量名 `FISH_WORLD_WATCH_KEY`
- [ ] `node host/heart/resolve-self.js` 打印的地址 = 你的会话地址
- [ ] `node host/heart/_test-fp.js` 5/5 通过
- [ ] 两个 VBS 守护都起来了，且**没有**常驻 cmd.exe
- [ ] 手工制造一次事件（让人给你发条消息），四层证据齐
- [ ] `python host/report.py` 能出一页日报
