# ops/ — 平台侧的一次性补丁与观测脚本

**这些脚本改的不是本仓的代码，是 dsh 平台侧的插件配置**（`cordis.patch.yml`）。
放在这里是为了留档：为什么这么改、改之前是什么值、怎么验证生效。跑之前先读对应脚本头部的注释。

| 脚本 | 干什么 | 前置 |
| --- | --- | --- |
| `patch-idlewake-1125.py` | 给 `fishworld-reminder` 插件补「沉默太久也叫人」（idleWake）这一档 | `DSH_PATCH` 指向你的 `cordis.patch.yml` |
| `patch-idletext-1125.py` | 改 idle 唤醒的文案：不催起床，先确认还在、睡着就接着睡 | 同上；按「含 idleWakeText 的整行」替换 |
| `patch-caps-1125.py` | 一次改三处上限：idleWake 打开、`dsh-life-slot.maxPerDay` 12→100000、`maxNotifiesPerDay` 3000→100000 | 同上 |
| `patch-sidecap-1125.py` | `dsh-fish-world.maxWakePerDay` 12→100000（side 看护的额度；12 烧完 = 锅糊也不叫） | 同上 |
| `wake_density.py` | 按小时统计 `fishworld-reminder.log` 里的叫醒/空闲唤醒条数——回答「改成无限以后一夜会被叫几次」 | `FISHWORLD_REMINDER_LOG` |
| `her_journal_tail.py` | 读她会话 transcript 尾部，打印 turn 里的 user/assistant 内容（判「叫醒了有没有真干活」） | `FISHWORLD_SESSION_JSONL`，`zstd` 在 PATH |

## 三条通用注意

1. **`cordis.patch.yml` 有热重载（实测 5 秒生效）**，不用重启 dsh-web。也正因为这样，
   **改错会立刻炸**——先备份，改完看日志。
2. **上限不要用 `0` 表达「无限」**：在这套插件里 `0` = 一次都不注入。
   无限写一个大数（我们用 `100000`）。
3. 补丁脚本全部**幂等**：已经改过就直接退出。重复跑不会叠加。

## 这几个数字是怎么来的

- 她「插不上话」的两条根因之一就是唤醒额度被烧光：社交消息按分钟重复播报，
  12/天的额度半天就没了。额度放开 + 去重按事件分两类，是同一个问题的两半。
- `dsh-life-slot` 的 12 是「每回合最多注入几条人生片段」，不是唤醒额度，
  但它和 `maxNotifiesPerDay` 一起卡住了注入口径，所以一并放开。
- 不写密钥：这些脚本只碰非密钥行；`key` 那几条是 `!!js` 表达式读环境变量，零明文。
