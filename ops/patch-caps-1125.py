# -*- coding: utf-8 -*-
"""1125 主人令：三件事一次改完（幂等）。

1) fishworld-reminder 打开「沉默太久也叫人」（idleWake*）。她的长 sleep 塞在后台 job 里，
   插件推送 source=fish-world 断不了 wait（引擎只认 kind=user），只有宿主 QQ 消息断得了。
2) dsh-life-slot 的 maxPerDay: 12 -> 100000（0 表示一次都不注入，不能用来表达无限）。
3) fishworld-reminder 的 maxNotifiesPerDay: 3000 -> 100000（同样不能用 0）。

不碰 key 行（那行是 !!js 表达式读 env，零明文）。
"""
import io
import os
import sys

PATCH = os.environ.get("DSH_PATCH") or os.path.expanduser("~/.dsh/profiles/web/cordis.patch.yml")

ANCHOR_EVENTS = "        events: {arrive: true, done: true}\n        quietHours: {}"

IDLE_BLOCK = """        events: {arrive: true, done: true}
        quietHours: {}
        # 1125 主人令：沉默太久也要叫人。她的长 sleep 都塞在后台 job 里，
        # 插件推送 source=fish-world 断不了 wait（引擎只认 kind=user），宿主 QQ 消息才断得了。
        # 计时起点 = 最后一次真叫醒；正常消息叫醒会重新起算，所以不会跟消息抢。
        idleWakeEnabled: true
        idleWakeMinutes: 45
        idleWakeText: "（空闲唤醒）安静了 45 分钟，看一眼现在在哪、包里有饭没有、力气够不够；该吃就吃，该干活就干活，别一直挂着等。" """

REPLACEMENTS = [
    # (old, new, 说明)
    ("        maxPerDay: 12\n", "        maxPerDay: 100000\n", "dsh-life-slot 每日上限"),
    ("        maxNotifiesPerDay: 3000\n", "        maxNotifiesPerDay: 100000\n", "fishworld-reminder 每日上限"),
]


def main() -> int:
    with io.open(PATCH, encoding="utf-8") as f:
        src = f.read()
    orig_len = len(src)

    # 1) idle wake block
    if "idleWakeEnabled" in src:
        print("[1] SKIP idleWakeEnabled already=%s" % str("idleWakeEnabled: true" in src))
    else:
        n = src.count(ANCHOR_EVENTS)
        if n != 1:
            print("[1] FAIL anchor events/quietHours count=%d" % n)
            return 2
        src = src.replace(ANCHOR_EVENTS, IDLE_BLOCK)
        print("[1] OK idleWake block inserted")

    # 2) caps
    for old, new, label in REPLACEMENTS:
        n = src.count(old)
        if n != 1:
            print("[2] FAIL %s anchor count=%d (old=%r)" % (label, n, old.strip()))
            return 2
        src = src.replace(old, new)
        print("[2] OK %s %s -> %s" % (label, old.strip(), new.strip()))

    with io.open(PATCH, "w", encoding="utf-8") as f:
        f.write(src)

    with io.open(PATCH, encoding="utf-8") as f:
        after = f.read()

    print("VERIFY size=%d (was %d)" % (len(after), orig_len))
    print("VERIFY idleWake lines=%d" % after.count("idleWake"))
    print("VERIFY maxPerDay:100000=%d  maxPerDay:12=%d" % (after.count("maxPerDay: 100000"), after.count("maxPerDay: 12")))
    print("VERIFY maxNotifiesPerDay:100000=%d  maxNotifiesPerDay:3000=%d"
          % (after.count("maxNotifiesPerDay: 100000"), after.count("maxNotifiesPerDay: 3000")))
    print("VERIFY key line still js-expr=%s" % str("process.env.FISH_WORLD_WATCH_KEY" in after))
    # 打印改动周边，肉眼确认缩进没串
    for i, line in enumerate(after.splitlines(), 1):
        if "maxPerDay: 100000" in line or "maxNotifiesPerDay: 100000" in line or "idleWakeEnabled" in line:
            print("LINE %d: %s" % (i, line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
