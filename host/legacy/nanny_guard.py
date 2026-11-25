# -*- coding: utf-8 -*-
"""nanny_guard.py —— 心跳的守护（无窗常驻）
每 60 秒数一遍 pythonw 里有没有 nanny_beat.py，没有就拉起来。
判据不只看进程：nanny_state.json 的 lastAt 超过 STALE_MS 也算死（进程在跑但卡住了）。
日志：nanny_guard.log
"""
import io, json, os, subprocess, time, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PYW = os.environ.get("PYTHONW") or "pythonw.exe"
BEAT = os.path.join(HERE, "nanny_beat.py")
STATE = os.path.join(HERE, "nanny_state.json")
LOG = os.path.join(HERE, "nanny_guard.log")
GUARD_LOG = os.path.join(HERE, "nanny_guard.log")
STALE_MS = 20 * 60 * 1000     # 心跳 7 分钟一轮；20 分钟没写 = 卡死
BEAT_GRACE_S = 200            # 刚拉起的这只给它 ~3 轮时间，别把正在跑活的杀掉
TICK = 60
NO_WIN = 0x08000000


def log(line):
    ts = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (ts, line))


def alive():
    """返回 (pid 或 None)。用 wmic 只看 pythonw 里跑 nanny_beat.py 的那只。"""
    try:
        p = subprocess.run(
            ["wmic", "process", "where", "name='pythonw.exe'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, timeout=30, creationflags=NO_WIN)
        txt = p.stdout.decode("utf-8", "replace")
        for ln in txt.splitlines():
            if "nanny_beat.py" in ln and "nanny_guard" not in ln:
                parts = [x for x in ln.split(",") if x.strip()]
                for x in reversed(parts):
                    if x.strip().isdigit():
                        return x.strip()
    except Exception as e:
        log("WMIC_FAIL %r" % e)
    return None


def age_ms():
    """心跳最后一次写 state 距今多少毫秒；state 不存在就退看日志 mtime。
    返回 int 毫秒；完全判不出就返回 None。"""
    try:
        st = json.load(io.open(STATE, encoding="utf-8"))
        return int(time.time() * 1000) - int(st.get("lastAt") or 0)
    except Exception:
        pass
    try:
        return int((time.time() - os.path.getmtime(os.path.join(HERE, "nanny_beat.log"))) * 1000)
    except Exception:
        return None


def fresh():
    age = age_ms()
    if age is None:
        return False, "unreadable"
    return age < STALE_MS, age


def kill(pid):
    try:
        p = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                           timeout=30, creationflags=NO_WIN)
        ok = p.returncode == 0
        log("KILL pid=%s rc=%d %s" % (pid, p.returncode,
                                      "ok" if ok else p.stderr.decode("utf-8", "replace")[:100]))
        return ok
    except Exception as e:
        log("KILL_FAIL pid=%s %r" % (pid, e))
        return False


def start():
    try:
        subprocess.Popen([PYW, BEAT], cwd=HERE, creationflags=NO_WIN,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("RESTART spawned")
    except Exception as e:
        log("RESTART_FAIL %r" % e)


def main():
    # 单实例锁：原子创建（O_CREAT|O_EXCL），抢不到就退出——防守护自己双开
    lock = os.path.join(HERE, "nanny_guard.pid")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        try:
            old = int(io.open(lock, encoding="utf-8").read().strip())
        except Exception:
            old = 0
        still = old and subprocess.run(["tasklist", "/FI", "PID eq %d" % old],
                                       capture_output=True, creationflags=NO_WIN
                                       ).stdout.decode("utf-8", "replace").find(str(old)) > 0
        if still:
            log("LOCK_HELD by pid=%d，本实例 pid=%d 退出" % (old, os.getpid()))
            return
        log("LOCK_STALE pid=%d 已不在，接管" % old)
        try:
            os.remove(lock)
        except Exception:
            pass
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)

    log("=== nanny_guard start pid=%d tick=%ds ===" % (os.getpid(), TICK))
    spawnedAt = time.time()
    while True:
        pid = alive()
        ok, age = fresh()
        # 刚拉起来的那只，给一轮宽限：它要先跑 beat + look 才写 state，中途 state 是空的
        grace = (time.time() - spawnedAt) < (BEAT_GRACE_S)
        if pid is None:
            log("BEAT_DEAD (no process) -> restart")
            start()
            spawnedAt = time.time()
        elif not ok and grace:
            log("BEAT_YOUNG age=%s 宽限中（刚拉起 %ds），不动" % (age, int(time.time() - spawnedAt)))
        elif not ok:
            # 真卡死的先杀掉，否则它会继续握着同一份 state/log，双开无法判定谁是活的
            log("BEAT_STALE age=%s -> kill %s then restart" % (age, pid))
            kill(pid)
            time.sleep(3)
            start()
            spawnedAt = time.time()
        else:
            log("OK pid=%s beat_age=%s" % (pid, age if isinstance(age, str) else "%ds" % (age // 1000)))
        time.sleep(TICK)


if __name__ == "__main__":
    main()