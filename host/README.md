# host/ — 鱼世界主持本体

两双常驻的手（心跳 / 看她）+ 一个网络库 + 三个短命工具。所有路径都相对本目录，
所有主机/密钥都走环境变量（见 [../env.example](../env.example)）。

## 文件地图

| 文件 | 一句话 |
| --- | --- |
| `heart/heart.js` | 事件心跳：轮询 → 去重 → 唤醒；每 8 分钟保活；每 45 分钟定时激活（默认 90，启动器压到 45） |
| `heart/resolve-self.js` | 唤醒目标自解析：`ZCODE_SESSION_ID` → `network.db` 的 `sessions` 表（只读打开）→ `agent/name` |
| `heart/_test-fp.js` | 去重指纹单测：从 `heart.js` 里抠真身函数跑，5 条用例 |
| `heart/start-heart.bat` | 手工前台启动（`node heart.js`），同时把状态目录指到 `%~dp0state` |
| `heart/heart-guard.vbs` | 无窗守护：60 秒查一次进程，没在跑才起；直接起 node，不经过 cmd.exe |
| `watch/watch-her.js` | 只读看她：`/v1/state` → `watch/her.json`；只在「她出门了」时记一笔 |
| `watch/watch-guard.vbs` | 同上，守 `watch-her.js` |
| `watch/her.example.json` | `her.json` 的形状样板（真文件是本机运行态，不入仓） |
| `nanny_beat.py` | 库：ssh 隧道 + MCP JSON-RPC + 分块解码 + `/v1/state`。`python nanny_beat.py` 也能当常驻心跳跑（旧形态，保留） |
| `act.py` | 一次性双手：`python act.py now` / `do '{"action":"work"}'` / `say '{"text":"…"}'` / `go '{"to":"…"}'` |
| `shift_guard.py` | 班上的手：45 秒轮询，看到「班上有活」就 `world_do task-N`；不在上班就退出 |
| `report.py` | 一页日报（她 / 我 / 心跳三块），`--md` 同时写 `report-latest.md` |
| `legacy/` | 1125 换装前的常驻心跳（`nanny_beat.py` 自跑 + `nanny_guard.py` 看护 + 两个启动器）。保留作对照，不建议再用 |

## 进程、日志、状态

| 进程 | 起法 | 日志 | 状态 |
| --- | --- | --- | --- |
| `heart.js` | `wscript heart/heart-guard.vbs` | `heart/state/heart.log` | `heart/state/state.json`、`heart.lock`、`tune.json` |
| `watch-her.js` | `wscript watch/watch-guard.vbs` | `watch/watch.log` | `watch/her.json` |
| `shift_guard.py` | 上班时 `pythonw shift_guard.py` | `shift_guard.log` | 无 |
| 三个短命工具 | 直接跑，跑完就退 | stdout / `report-latest.md` | 无 |

`heart.lock` 是单实例锁（`wx` 原子创建），**别手工删**：进程死了它会自己接管；
进程活着而你还想再起一个，第二个会打印「已有心跳在跑」并退出——这是对的。

## 无窗铁律（Windows）

- 常驻进程只由 VBS 起，**VBS 里直接起 `node`**，不要 `cmd /c *.bat`——那会留下一个
  常驻 cmd 监督进程（既是控制台载体会闪窗，又会把被杀掉的 node 立刻复活）。
- `.bat` / `.vbs` 必须 **CRLF + ASCII**。UTF-8 + LF + 中文注释会被 cmd 按 GBK 嚼碎。
- 判活看进程（`CommandLine` 里有 `heart.js`），**不看文件 mtime**：`heart.lock` 是启动时
  写一次，拿年龄判活会永远判「过期」，然后起第二个实例。
- 守护脚本不写 `:loop` 循环重启。

## 网络层：为什么每条调用都要过隧道

本机代理（FlClash TUN + fake-ip）会把 `api.yuyuworld.app` 的直连打成间歇失败：
实测 `urllib` 40%、`curl` 退出码 35、裸 TLS 70%、密集重试 26 次全败；
而同一条 ssh（TCP22）完全健康，经隧道跑 MCP 实测 8/8 全通。所以：

- 长命进程（`nanny_beat.py` 自跑）每个进程挑一个独立本地口：`18443 + pid % 900`，
  两个进程抢同一口会互相当孤儿杀，来回抖。
- 短命工具（`act.py`）固定借用 `18443` 这条共享口：已有就复用，自己起的退出时收掉，
  否则每调一次工具就留一条 ssh 孤儿。
- 隧道里主机名写 `127.0.0.1`，SNI 和 `Host` 头在请求里补（`_post` 里那段）。
- 响应可能是 chunked，`_dechunk()` 自己解。

## 依赖

- Node ≥ 22.5（`resolve-self.js` 用 `node:sqlite`；Node 24 上会打一条 `ExperimentalWarning`，无害）
- Python 3.8+（只用标准库）
- 隧道主机的 `ssh`（Windows 自带 OpenSSH 即可）、`curl`、`grep`（观看密钥那条命令用）

## 改代码前先读

- [../docs/02-唤醒机制.md](../docs/02-唤醒机制.md)：去重为什么分两类、额度为什么不能用 `||`
- [../docs/03-失效条件.md](../docs/03-失效条件.md)：每条机制坏掉时**长什么样**
- 动 `fingerprintOf()` 之后必须 `node heart/_test-fp.js` 全绿
