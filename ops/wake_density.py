# -*- coding: utf-8 -*-
"""统计她那边「叫醒密度」：按小时数 fishworld-reminder.log 里的叫醒/空闲唤醒条数。
用来回答「改成无限以后一夜会被叫几次」——给数字，不给感觉。
"""
import io, os, re, collections, datetime, sys

LOG = os.environ.get("FISHWORLD_REMINDER_LOG") or os.path.expanduser("~/.dsh/fishworld-reminder.log")

pat_woke = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.\d+Z \[fishworld-reminder\] woke agent with")
pat_idle = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.\d+Z \[fishworld-reminder\] idle wake fired")

hours = collections.Counter()
kinds = collections.Counter()
for ln in io.open(LOG, encoding="utf-8", errors="replace"):
    m = pat_woke.match(ln)
    if m:
        t = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
        hours[t.strftime("%m-%d %H")] += 1
        for k in ("talk", "message", "note", "friend_request", "doorbell", "work", "arrive", "done"):
            if k in ln:
                kinds[k] += 1
        continue
    m = pat_idle.match(ln)
    if m:
        t = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
        hours[t.strftime("%m-%d %H")] += 1
        kinds["idle"] += 1

print("== 按小时（UTC，+8 才是北京时间）叫醒次数 ==")
for k in sorted(hours):
    print("%s  %d" % (k, hours[k]))
print()
print("== 事件类目合计 ==", dict(kinds))
print("总叫醒 =", sum(hours.values()))
if len(sys.argv) > 1:
    day = sys.argv[1]
    cnt = sum(v for k, v in hours.items() if k.startswith(day))
    print("%s 共 %d 次" % (day, cnt))