# -*- coding: utf-8 -*-
"""shift_guard.py —— 班上的手（不是常驻，人一上班我起一个，下班自己退）
每 45 秒读一次 world_now：看到「班上有活」就立刻 world_do task-N 处理掉。
活必须在 10 分钟内处理，所以轮询要快；一次只处理一件，处理完再看。

用法：pythonw shift_guard.py    （自己判断：没在上班就退出）
日志：shift_guard.log
"""
import io, os, re, sys, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import act

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "shift_guard.log")
TICK = 45
MAX_MIN = 75          # 一班 60 分钟，最多守 75 分钟就退，防挂着不走


def log(line):
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (datetime.datetime.now().strftime("%m-%d %H:%M:%S"), line))


def parse_tasks(txt):
    """从 world_now 里捞出「班上有活」那一段的选项编号：task-1 / task-2 ..."""
    if "班上有活" not in txt:
        return [], None
    seg = txt.split("班上有活", 1)[1].split("身体：" if "身体：" in txt else "\n\n", 1)[0]
    ids = re.findall(r"task-(\d+)", seg)
    return sorted(set(ids)), seg.strip().splitlines()[0] if seg.strip() else None


def on_duty(txt):
    return "在做：在" in txt and "打零工" in txt


def brief(txt):
    """一行摘出「有没有班活 + 在做那行」，事后能判「世界没给活」还是「我瞎了」。"""
    doing = ""
    for ln in txt.splitlines():
        if ln.startswith("在做："):
            doing = ln.strip()
            break
    return "%s | %s" % ("有活" if "班上有活" in txt else "无活", (doing or "(无在做行)")[:100])


def main():
    log("=== shift_guard start pid=%d tick=%ds ===" % (os.getpid(), TICK))
    t0 = time.time()
    handled = 0
    idle = 0
    while (time.time() - t0) < MAX_MIN * 60:
        txt, err = act.call("now")
        if err or not txt:
            log("NOW_FAIL %s" % (err or "empty")[:120])
            time.sleep(TICK)
            continue
        if not on_duty(txt):
            log("OFF_DUTY 不在班上了 -> 退出（处理 %d 件）" % handled)
            return
        ids, head = parse_tasks(txt)
        if not ids:
            # 1125 补观测：这里原来完全静默（11-25 夜班 57 分钟零日志，
            # 事后判不出是「世界没派活」还是「我解析没匹配上」）。
            idle += 1
            if idle == 1 or idle % 10 == 0:
                log("ON_DUTY_NO_TASK 第%d轮 | %s" % (idle, brief(txt)))
            time.sleep(TICK)
            continue
        idle = 0
        done = False
        for tid in ids:
            res, e2 = act.call("do", {"id": "task-" + tid})
            if e2 or not res:
                log("TASK_FAIL task-%s %s" % (tid, (e2 or "")[:100]))
                continue
            if res.startswith("[E_") or "不" in res[:6]:
                log("TASK_REJ task-%s %s" % (tid, res[:100]))
                continue
            handled += 1
            done = True
            log("TASK_OK task-%s 共%d件 | %s" % (tid, handled, res.splitlines()[0][:90]))
            break
        if not done:
            log("TASK_NONE_OK 有活但都不接：%s" % (head or "")[:100])
        time.sleep(20)
    log("TIMEOUT 守了 %d 分钟，退出（处理 %d 件）" % (MAX_MIN, handled))


if __name__ == "__main__":
    main()