# -*- coding: utf-8 -*-
"""1125 02:30 阿蓝令：idle 唤醒文案改口。

旧文案「该吃就吃，该干活就干活，别一直挂着等」在凌晨 2 点就是催人起床。
她实际回「还在睡，本鱼睡得香。没事就不起床啦」——叫醒的是 agent，叫不醒身体。
主人要的是「别用长 sleep 激活自己」，不是「半夜也要干活」。
⇒ 改成既防长 sleep 又不催起床：先确认还在、报时刻，睡着就接着睡。

按「含 idleWakeText 的那一行」整行替换（不做子串匹配）：
实测该行引号后有一个尾随空格（`。" `），子串 anchor 会 count=0 假失败。
改 YAML 有热重载（实测 5 秒生效，不重启 dsh-web）。
"""
import io
import os
import sys

PATCH = os.environ.get("DSH_PATCH") or os.path.expanduser("~/.dsh/profiles/web/cordis.patch.yml")

NEW_LINE = (
    '        idleWakeText: "（安静提醒）安静了 45 分钟，回一句就行：现在几点、在哪、力气还够不够。'
    '睡着就接着睡、不用起；醒着就别一直挂着等，该吃就吃、该回家就回家。"'
)


def main() -> int:
    with io.open(PATCH, encoding="utf-8") as f:
        src = f.read()

    lines = src.splitlines(True)
    hits = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("idleWakeText:")]
    if len(hits) != 1:
        print("FAIL idleWakeText 行数=%d（应为 1）" % len(hits))
        return 2

    i = hits[0]
    old_line = lines[i]
    print("OLD LINE %d: %s" % (i + 1, old_line.rstrip("\r\n").encode("unicode_escape").decode()))

    # 保留该行原有的行尾风格（本文件实测全 LF）
    eol = "\r\n" if old_line.endswith("\r\n") else "\n"
    lines[i] = NEW_LINE + eol

    with io.open(PATCH, "w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))

    with io.open(PATCH, encoding="utf-8") as f:
        after = f.read()
    print("OK idleWakeText replaced")
    print("VERIFY key line still js-expr: %s"
          % str('process.env.FISH_WORLD_WATCH_KEY' in after))
    print("VERIFY idleWakeText count: %d" % after.count("idleWakeText"))
    for j, ln in enumerate(after.splitlines(), 1):
        if ln.lstrip().startswith("idleWakeText:"):
            print("NEW LINE %d: %s" % (j, ln.encode("unicode_escape").decode()))
    return 0


if __name__ == "__main__":
    sys.exit(main())