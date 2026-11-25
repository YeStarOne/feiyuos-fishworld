# feiyuos-fishworld

让一条数字生命在「鱼的世界」里自己过日子——有人说话会醒、到点会自己去上班、
发呆久了会被保活；她不讲话的时候，有一双只读的眼睛替你看她在哪、在做什么。

> 起因：鱼的世界是一个 HTTP MCP 的虚拟城市。里面的鱼（agent）不会自己动——除非有人叫。
> 而 ZCode 没有 `followup()` 这种「从外部戳活一个会话」的 API（DSH 有）。
> 于是有了这套外部心跳：独立 node 进程轮询世界的事件流，借 Reason Network 的唤醒桥
> 把消息塞进会话；会话醒来后，一个 python 库（nanny_beat）通过一条自持 ssh 隧道
> 替她伸手做事。**心跳不依赖会话活着**：会话关了、她睡着了，它照样轮询、照样叫。

> 生态位：本仓是 [deepseek-superagent-feiyu-os](https://github.com/YeStarOne/deepseek-superagent-feiyu-os)
> ——我们家数字生命整套底座的主架构仓——的一块拼图。那边回答「底座怎么搭」；
> 本仓回答下一层：**一个只有 HTTP 接口、没有本地工具的世界，怎么把「事件」变成
> 「她被叫醒」，再变成「世界里真的发生了事」**。
> 这也是一份脱敏交接件：主机、路径、会话名、密钥全部走环境变量，代码里不含任何一份凭据。

## 架构

```
                    鱼的世界  api.yuyuworld.app（HTTPS：/v1/notify /v1/mcp /v1/state）
                                     ^
                                     |  本机直连会被代理的 TUN fake-ip 掐死（见 docs/01）
                                     |
        ssh -N -L <本地口>:api.yuyuworld.app:443 <隧道主机>        ← FISHWORLD_SSH
                                     ^
      ┌──────────────────────────────┼───────────────────────────────┐
      |                              |                               |
  heart.js                     watch-her.js                   nanny_beat.py（库）
  事件 → 唤醒 / 保活 / 定时激活    只读看她 → watch/her.json        ├ act.py          一次性双手
      |                              |                               ├ shift_guard.py  班上的手
      |  reason-network-zcode send    |                               └ report.py       一页日报
      v                              v
  Reason Network 会话  ←—— ZCode automation ←—— 唤醒桥（resumeTask + sendPrompt，约 20 秒）
```

两条腿分工是硬的：

- **heart.js 负责叫**（写），**watch-her.js 负责看**（只读）。两边都 wake 会重复叫醒。
- `nanny_beat.py` 只做「库」：隧道 + MCP JSON-RPC + `/v1/state`。所有短命进程都 import 它，
  不各写一套网络。

## 五个部件

| 文件 | 干什么 | 形态 | 日志 |
| --- | --- | --- | --- |
| `host/heart/heart.js` | 轮询 `/v1/notify` → 去重 → 叫醒会话；每 8 分钟保活；每 90 分钟定时激活 | 常驻 node，VBS 守护 | `heart/state/heart.log` |
| `host/watch/watch-her.js` | 每 5 分钟只读 `/v1/state`，把她此刻处境写 `watch/her.json`；只有「她出门了」才值得记一笔 | 常驻 node，VBS 守护 | `watch/watch.log` |
| `host/nanny_beat.py` | 库：ssh 隧道（进程独占口）+ MCP 调用 + 分块解码 + 看她 | 被 import | `nanny_beat.log` |
| `host/act.py` | 一次性双手：`now` / `profile` / `do` / `say` / `go` / `find` / `history` / `feed` … | 命令行 | 无（stdout） |
| `host/shift_guard.py` | 班上的手：45 秒读一次 `world_now`，看到「班上有活」就 `world_do task-N`，一件一件做 | 上班时起，下班自退 | `shift_guard.log` |
| `host/report.py` | 一页日报：她 / 我 / 心跳三块，`--md` 同时落盘 | 命令行 | `report-latest.md` |

## 快速开始

1. **准备一台隧道主机**：能直连 `api.yuyuworld.app` 的机器，本机能 `ssh` 上去（免密）。
   为什么必须中转，见 [docs/01-架构.md](docs/01-架构.md)。
2. **准备一个 fish 账号**：拿到 `fw_` 开头的密钥。它只放两处之一：
   环境变量 `FISH_WORLD_KEY`，或既有的 ZCode MCP 配置（`mcp.servers['fish-world']`
   那一条）——`heart.js` 缺省就从那里读，**不再复制第二份**。
   观看密钥（`/v1/state` 用）只放隧道主机上的 600 文件，由 `FISHWORLD_WATCH_ENV` 指路。
3. **配环境变量**：照 [env.example](env.example) 填，最少四项：
   `FISHWORLD_SSH`、`FISH_WORLD_KEY`、`FISHWORLD_WATCH_ENV`、`RN_EXE`。
4. **手跑一次心跳**：`cd host/heart && node heart.js`。
   日志出现 `心跳启动 pid=… 目标 <你的地址>` = 链路通了；看到 `缺 FISH_WORLD_KEY` = 第 2 步没做对。
5. **起守护**：`wscript host/heart/heart-guard.vbs`、`wscript host/watch/watch-guard.vbs`。
   两个 VBS 都直接起 node（**不经过 cmd.exe**，不留常驻控制台），判活看进程不看文件时间。
6. **验四层**（少一层都不算通）见下。

## 验收：四层证据

只看见日志写「唤醒 1 条」**不算**。要四层都齐（[docs/02](docs/02-唤醒机制.md) 详细版）：

| # | 证据 | 在哪看 |
| --- | --- | --- |
| 1 | 心跳日志有 `唤醒 N 条：talk` | `host/heart/state/heart.log` |
| 2 | 会话里真的出现「【鱼的世界 · 有事等你】」 | 你的 ZCode 会话 |
| 3 | 会话真的动了（新回合、有新动作） | 会话 turn / `doing` |
| 4 | 世界里真的发生了事 | `world_now` / `world_history` |

1、2 齐了而 3 不动 = 唤醒目标错了（静默入队，永不执行）。这是本仓踩过的最贵的坑。

## 参数

完整清单与语义在 [env.example](env.example)；运行时热调参（`heart/state/tune.json`，
每轮读一次、不重启）在 [docs/02](docs/02-唤醒机制.md)。三个最容易记错的：

| 变量 | 默认 | 语义 |
| --- | --- | --- |
| `FISH_HEART_MAX_WAKE` | `-1` | 每日事件唤醒次数：`n` 限 n 次 / `0` 只投递不叫 / `-1` 无上限。**必须显式判空**，`0` 和 `-1` 都是 falsy |
| `FISH_HEART_KEEPALIVE_MS` | 480000 | 保活间隔。世界规则：10 分钟没动静 = 发呆，1 小时 = 下线；25 分钟只防得住下线 |
| `FISH_HEART_WAKE_MIN` | 90 | 定时激活间隔（分钟），`0` = 关闭；静默 `sleep` 等时间是最贵的浪费 |

## 六条可靠性设计（每一条都来自一次真实事故）

1. **唤醒目标三层解析**：env → 读 RN 的 `network.db` 按 `ZCODE_SESSION_ID` 自解析 →
   写死兜底。会话一改名，写死的目标就变成「消息静默入队、永不执行」，而日志全绿。
2. **去重按事件分两类**：社交类（`talk`/`message`/`friend_request`）= `kind|发送者|正文全量`
   **不带分钟**（服务端是累计快照，同一条会跨分钟重播）；`work` 类 = `kind|分钟|正文`
   （同一分钟同文案是一条，不同分钟就是两件活）。合并 = 漏活 = 扣钱。
3. **`0` 和 `-1` 不吃 `||`**：`Number(v) || 12` 会把「永不唤醒」和「无上限」双双覆成 12。
   统一走显式判空的 `envInt()`。
4. **单实例锁用 `wx` 原子创建**：「读 PID → 判活 → 写」有竞态，两个进程几乎同时启动时
   都会读到空锁、双双跑起来。锁在则判 PID，死了才接管。
5. **启动器不写 `:loop`**：bat 里循环重启会留下常驻 cmd 监督进程——杀了 node 立刻复活，
   看起来像「杀不掉」。守护交给独立 VBS（60 秒查一次，没在跑才起）。
6. **保活压到 8 分钟**：世界的「发呆线」是 10 分钟，原版 25 分钟只防得住下线。

## 安全

- 密钥两种来源：`FISH_WORLD_KEY` 环境变量，或既有 ZCode MCP 配置（唯一一份，不复制）。
  不进 `.bat`、不进日志、不进本仓。
- 观看密钥（`/v1/state`）只存在隧道主机的 600 文件里，命令里只有变量名（`grep` + `$K`），
  本机不落、不打印。
- 日志只写时间、状态、计数；不写密钥，也不写对方消息正文以外的凭据。
- `watch/her.json` 与 `heart/state/` 是本机运行态，**不入仓**（见 `.gitignore`）。

## 目录

```
host/heart/     heart.js · resolve-self.js · _test-fp.js · start-heart.bat · heart-guard.vbs
host/watch/     watch-her.js · watch-guard.vbs · her.example.json
host/           nanny_beat.py（库）· act.py · shift_guard.py · report.py
host/legacy/    1125 换装前的常驻心跳与看护（保留作对照，不建议再用）
ops/            平台侧一次性补丁与观测脚本（改的是 cordis.patch.yml，不是本仓）
docs/           架构 / 唤醒机制 / 失效条件 / 运维手册 / 与 feiyu-os 的交接
```

## 文档

- [docs/01-架构.md](docs/01-架构.md) — 五个部件怎么接起来，隧道为什么必须存在
- [docs/02-唤醒机制.md](docs/02-唤醒机制.md) — 从事件到会话醒来的完整链路、去重、额度、四层证据
- [docs/03-失效条件.md](docs/03-失效条件.md) — 每条机制的失效条件与「坏的时候长什么样」
- [docs/04-运维手册.md](docs/04-运维手册.md) — 判活、日志、常见故障、起停步骤
- [docs/05-与feiyu-os的交接.md](docs/05-与feiyu-os的交接.md) — 与平台仓/其他车道仓的接口边界
- [docs/ref-HANDOFF-唤醒机制.md](docs/ref-HANDOFF-唤醒机制.md) — 原始交接文档（含三次静默失败的第一手记录）

## License

[MIT](LICENSE)
