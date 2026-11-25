# -*- coding: utf-8 -*-
"""report.py —— 一页写清「她和我的现状」，给主人看也给我自己看。
一次一根：读她(只读看电影密) + 读我 + 读心跳/守卫状态 → 一页文字。
用法：python report.py        （--md 同时写 report-latest.md）
"""
import io, json, os, sys, time, datetime, atexit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nanny_beat as nb


def _reap():
    """report 也是短命进程：自己起的隧道退出时收掉，别每跑一次留一条 ssh 孤儿。"""
    p = nb._tunnel.get("p")
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass


atexit.register(_reap)


def heartbeat_status():
    """心跳/守卫/班上手的实况。判活不看进程在，看它该写的有没有在写。

    1125 换装：老的 nanny_beat.py/nanny_guard.py 已退役，现在是
    heart.js（轮询+保活+定时激活）/ watch-her.js（只读看她）/ shift_guard.py（班上的手）。
    """
    def pid_of(key):
        import subprocess
        try:
            p = subprocess.run(["wmic", "process", "where", "name='pythonw.exe' or name='node.exe'",
                                "get", "ProcessId,CommandLine", "/format:csv"],
                               capture_output=True, timeout=25, creationflags=0x08000000)
            for ln in p.stdout.decode("utf-8", "replace").splitlines():
                if key in ln:
                    ids = [x.strip() for x in ln.split(",") if x.strip().isdigit()]
                    if ids:
                        return ids[-1]
        except Exception:
            pass
        return None

    out = {}
    # 心跳换成 heart.js 之后，状态落盘在 heart/state/state.json（老 nanny_state.json 不再更新）
    st = {}
    for cand in (os.path.join(HERE, "heart", "state", "state.json"),
                 os.path.join(HERE, "nanny_state.json")):
        try:
            st = json.load(io.open(cand, encoding="utf-8"))
            out["state_file"] = os.path.basename(os.path.dirname(cand)) + "/" + os.path.basename(cand)
            break
        except Exception:
            continue
    last = st.get("lastAt") or 0
    age = int(time.time() - last / 1000) if last else None
    out["beat_pid"] = pid_of("heart.js")
    out["beat_age_s"] = age
    out["polls"] = st.get("polls")
    out["beatFail"] = st.get("beatFail", 0)
    out["lookFail"] = st.get("lookFail", 0)
    out["wakes"] = st.get("wakes")
    out["activations"] = st.get("activations")
    out["lastLine"] = st.get("lastLine")
    out["watch_pid"] = pid_of("watch-her.js")
    out["shift_pid"] = pid_of("shift_guard.py")
    return out


def tail(path, n=1):
    try:
        lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
        return lines[-n:] if lines else []
    except Exception:
        return []


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    hb = heartbeat_status()
    brief, err, her, where = nb.look()
    me, merr = nb.beat()

    L = []
    L.append("═ 奶妈的日报 · %s ═" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    L.append("")
    L.append("【她】")
    if err:
        L.append("  读不到：" + str(err))
    else:
        doing = (her.get("doing") or {}).get("name") or "—"
        body = her.get("body") or {}
        L.append("  %s" % brief)
        L.append("  位置：%s（%s）" % (where, (her.get("where") or {}).get("door") or "—"))
        L.append("  身体：%s / %s / %s%s" % (body.get("full"), body.get("energy"), body.get("feel"),
                                          "" if not body.get("ill") else " · 病:" + str(body.get("ill"))))
        L.append("  在做：%s（%s 起）" % (doing, (her.get("doing") or {}).get("since")))
        L.append("  上次动静：%s（%s）" % (her.get("last_call"), her.get("presence")))
    L.append("")
    L.append("【我】")
    L.append("  " + (me if me else "心跳失败: " + str(merr)))
    L.append("")
    L.append("【心跳】")
    L.append("  heart pid=%s 上次轮询 %ss 前 | 轮询%s次 | 叫醒%s次 | 激活%s次 | 状态文件 %s" % (
        hb["beat_pid"], hb["beat_age_s"], hb["polls"], hb["wakes"], hb["activations"], hb.get("state_file")))
    L.append("  看她 pid=%s（只读）| 班上守卫 pid=%s" % (hb["watch_pid"], hb["shift_pid"]))
    L.append("  最新一格：" + (hb.get("lastLine") or "—"))
    b1 = tail(os.path.join(HERE, "heart", "state", "heart.log"), 1)
    if b1:
        L.append("  heart.log：" + b1[0])
    w1 = tail(os.path.join(HERE, "watch", "watch.log"), 1)
    if w1:
        L.append("  watch.log：" + w1[0][:150])
    L.append("")
    txt = "\n".join(L)
    print(txt)
    if "--md" in sys.argv:
        p = os.path.join(HERE, "report-latest.md")
        io.open(p, "w", encoding="utf-8").write("```\n" + txt + "\n```\n")
        print("\n(已写 %s)" % p)


if __name__ == "__main__":
    main()