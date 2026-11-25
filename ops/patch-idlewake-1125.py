# -*- coding: utf-8 -*-
"""给 fishworld-reminder 补上「沉默太久也叫人」这一档。

只改 profiles/web/cordis.patch.yml 里 fishworld-reminder 那一块(按 events/quietHours 两行做锚点)。
幂等:已经有 idleWakeEnabled 就直接退出。不碰 key 行(那行是 !!js 表达式,取 env,零明文)。
"""
import io
import os
import sys

PATCH = os.environ.get("DSH_PATCH") or os.path.expanduser("~/.dsh/profiles/web/cordis.patch.yml")

OLD = "        events: {arrive: true, done: true}\n        quietHours: {}"

NEW = """        events: {arrive: true, done: true}
        quietHours: {}
        # 1125 阿蓝令：沉默太久也要叫人。她的长 sleep 都塞在后台 job 里，
        # 插件推送 source=fish-world 断不了 wait（引擎只认 kind=user），宿主 QQ 消息才断得了。
        # 计时起点 = 最后一次真叫醒；正常消息叫醒会重新起算，所以不会跟消息抢。
        idleWakeEnabled: true
        idleWakeMinutes: 45
        idleWakeText: "（空闲唤醒）安静了 45 分钟，看一眼现在在哪、包里有饭没有、力气够不够；该吃就吃，该干活就干活，别一直挂着等。" """


def main() -> int:
    with io.open(PATCH, encoding="utf-8") as f:
        src = f.read()

    if "idleWakeEnabled" in src:
        print("SKIP already has idleWakeEnabled=%s"
              % str("idleWakeEnabled: true" in src))
        return 0

    n = src.count(OLD)
    if n != 1:
        print("FAIL anchor count=%d" % n)
        return 2

    with io.open(PATCH, "w", encoding="utf-8") as f:
        f.write(src.replace(OLD, NEW))

    with io.open(PATCH, encoding="utf-8") as f:
        after = f.read()
    print("OK idleWake lines=%d size=%d" % (after.count("idleWake"), len(after)))
    print("key line still js-expr: %s"
          % str("process.env.FISH_WORLD_WATCH_KEY" in after))
    return 0


if __name__ == "__main__":
    sys.exit(main())