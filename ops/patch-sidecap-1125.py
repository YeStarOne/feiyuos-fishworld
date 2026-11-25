# -*- coding: utf-8 -*-
"""1125 阿蓝令补漏：dsh-fish-world 的 maxWakePerDay 12 -> 100000。

这个闸管 side 看护（锅糊这类硬时限告警）。源码注释写明：
  「side-done 全批豁免 10min 间隔闸（锅糊不可逆，硬时限）；12/天额度闸照走」
⇒ 12 烧完 = 锅糊也不叫。必须一起放开。

幂等。只改这一行，不碰别的 maxWakePerDay/PerDay 写法不同的地方。
"""
import io
import os
import sys

PATCH = os.environ.get("DSH_PATCH") or os.path.expanduser("~/.dsh/profiles/web/cordis.patch.yml")
OLD = "        maxWakePerDay: 12\n"
NEW = "        maxWakePerDay: 100000\n"


def main() -> int:
    with io.open(PATCH, encoding="utf-8") as f:
        src = f.read()

    if OLD not in src:
        print("SKIP 没有 `maxWakePerDay: 12`（可能已改过）")
        n = src.count("maxWakePerDay: 100000")
        print("现在 maxWakePerDay: 100000 出现 %d 次" % n)
        return 0

    n = src.count(OLD)
    if n != 1:
        print("FAIL anchor count=%d（应为 1）" % n)
        return 2

    src = src.replace(OLD, NEW)
    with io.open(PATCH, "w", encoding="utf-8") as f:
        f.write(src)

    with io.open(PATCH, encoding="utf-8") as f:
        after = f.read()
    print("OK maxWakePerDay 12 -> 100000")
    print("VERIFY maxWakePerDay: 100000 出现 %d 次" % after.count("maxWakePerDay: 100000"))
    print("VERIFY key line still js-expr: %s" % str("process.env.FISH_WORLD_WATCH_KEY" in after))
    for i, line in enumerate(after.splitlines(), 1):
        if "maxWakePerDay" in line:
            print("LINE %d: %s" % (i, line))
    return 0


if __name__ == "__main__":
    sys.exit(main())