# -*- coding: utf-8 -*-
"""nanny_beat.py —— 阿蓝的心跳（无窗常驻）
两件事，每 BEAT_MIN 分钟一轮：
  1) 保活：调一次 world_profile（任意工具调用都算一次动静；10 分钟没动静 = 发呆，1 小时 = 下线）
  2) 看她：ssh 到服务器用观看密钥读 /v1/state，只读、不惊动她
所有密钥只从既有文件读，绝不打印、绝不落日志。

⭐ 为什么要 ssh 隧道：本机 FlClash（TUN + fake-ip 198.18.0.20）把到 api.yuyuworld.app 的
   直连搞成间歇失败（实测 urllib 40%、curl -35、裸 TLS 70%、密集重试 26 次全败），
   而同一条 ssh(TCP22) 完全健康、经隧道跑 MCP 实测 8/8 全通。所以 MCP 一律走自持隧道。
日志：nanny_beat.log（append，UTF-8）
"""
import json, os, io, time, socket, subprocess, sys, datetime
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.environ.get("ZCODE_CONFIG") or os.path.join(
    os.path.expanduser("~"), ".zcode", "cli", "config.json")
REMOTE = "https://api.yuyuworld.app/v1/mcp"
LPORT = 18443 + (os.getpid() % 900)   # ★每进程一个口：两个进程抢同一口会互相当孤儿杀，来回抖
URL = "https://127.0.0.1:%d/v1/mcp" % LPORT   # 主机名写 IP：SNI 靠 Host 头补（见 _post）
HOST_HDR = "api.yuyuworld.app"
LOG = os.path.join(HERE, "nanny_beat.log")
STATE = os.path.join(HERE, "nanny_state.json")
DB = os.environ.get("RN_DB") or os.path.join(
    os.path.expanduser("~"), ".reason", "network", "network.db")
BEAT_MIN = 7          # < 10 分钟发呆线，留 3 分钟余量
HOST = os.environ.get("FISHWORLD_SSH") or ""   # ★必填：能直连 api.yuyuworld.app 的那台机器（ssh 隧道用）
NO_WIN = 0x08000000


def whoami():
    """自解析本会话在 RN 里的名字：env 里的 session-id → network.db sessions 表。
    改名后自动跟上，不写死。失败才回落到硬编码兜底。"""
    env = os.environ.get("FISH_HEART_TARGET")
    if env:
        return env, "env"
    sid = os.environ.get("ZCODE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        try:
            import sqlite3
            con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)
            for agent in ("zcode", "cli"):
                cur = con.execute("select name from sessions where key=?", (agent + ":" + sid,))
                row = cur.fetchone()
                if row and row[0]:
                    con.close()
                    return "yestar/" + row[0], "db"
            con.close()
        except Exception:
            pass
    return os.environ.get("RN_FALLBACK_TARGET", "yestar/me"), "fallback"

# 本机 IPv6 不稳，强制 A 记录
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _orig(h, p, socket.AF_INET, t, pr, fl)

# ── 隧道：FlClash TUN 会把 api.yuyuworld.app 的直连打坏，MCP 一律经 ssh(TCP22) 转 ──
_tunnel = {"p": None, "at": 0}


def _port_open():
    try:
        s = socket.create_connection(("127.0.0.1", LPORT), timeout=3)
        s.close()
        return True
    except Exception:
        return False


def _kill_orphans(keep_pid=None):
    """清掉本进程端口上的遗留 ssh。★必须跳过自己的那条，否则自杀自己的活隧道。"""
    try:
        p = subprocess.run(["wmic", "process", "where", "name='ssh.exe'",
                            "get", "ProcessId,CommandLine", "/format:csv"],
                           capture_output=True, timeout=30, creationflags=NO_WIN)
        mine = str(keep_pid) if keep_pid else None
        for ln in p.stdout.decode("utf-8", "replace").splitlines():
            if ("%d:" % LPORT) in ln and HOST_HDR in ln:
                pid = [x for x in ln.split(",") if x.strip().isdigit()]
                if pid and pid[-1] != mine:
                    subprocess.run(["taskkill", "/PID", pid[-1], "/F"], capture_output=True,
                                   timeout=20, creationflags=NO_WIN)
                    log("TUNNEL_ORPHAN_KILL pid=%s" % pid[-1])
    except Exception as e:
        log("TUNNEL_ORPHAN_SCAN_FAIL %r" % e)


def tunnel_up():
    """确保 127.0.0.1:LPORT 有一条活隧道。顺序=自持的活→端口已开就借用→才重建。"""
    p = _tunnel["p"]
    if p is not None and p.poll() is None and (time.time() - _tunnel["at"]) < 3600:
        return True
    # 端口上已经有隧道（可能是刚自己起的，也可能是同端口别人起的）：直接借用，绝不去杀
    if _port_open():
        _tunnel["p"] = None
        _tunnel["at"] = time.time()
        if p is None or p.poll() is not None:
            log("TUNNEL_ADOPT existing 127.0.0.1:%d" % LPORT)
        return True
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    _kill_orphans()
    time.sleep(1.0)
    try:
        t = subprocess.Popen(
            ["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
             "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3",
             "-N", "-L", "%d:%s:443" % (LPORT, HOST_HDR), HOST],
            creationflags=NO_WIN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log("TUNNEL_SPAWN_FAIL %r" % e)
        return False
    time.sleep(3.5)
    if t.poll() is None:
        _tunnel["p"] = t
        _tunnel["at"] = time.time()
        log("TUNNEL_UP pid=%d -> 127.0.0.1:%d" % (t.pid, LPORT))
        return True
    log("TUNNEL_DIED_EARLY rc=%s" % t.returncode)
    _tunnel["p"] = None
    return _port_open()


def log(line):
    ts = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (ts, line))


def key():
    """fw_ 密钥：env FISH_WORLD_KEY 优先，其次读既有 ZCode MCP 配置（唯一一份，不复制到别处）。"""
    env = os.environ.get("FISH_WORLD_KEY")
    if env:
        return env
    j = json.load(io.open(CFG, encoding="utf-8"))
    h = j["mcp"]["servers"]["fish-world"]["headers"]["Authorization"]
    return h.split(" ", 1)[1]


def _dechunk(b):
    """解 Transfer-Encoding: chunked。裸 socket 不像 urllib 会替你解，不解就把 "3e7\\r\\n{" 当 JSON。"""
    out = []
    while True:
        i = b.find(b"\r\n")
        if i < 0:
            break
        try:
            n = int(b[:i].split(b";")[0].strip(), 16)
        except Exception:
            break
        b = b[i + 2:]
        if n == 0:
            break
        out.append(b[:n])
        b = b[n + 2:]
    return b"".join(out)


def _post_once(data, hdrs, timeout=20):
    """经隧道裸 TLS 发一个 POST，返回 (status, body, resp_headers)。SNI 用真主机名。"""
    import ssl
    s = ssl.create_default_context().wrap_socket(
        socket.create_connection(("127.0.0.1", LPORT), timeout=timeout),
        server_hostname=HOST_HDR)
    try:
        s.settimeout(timeout)
        head = ["POST /v1/mcp HTTP/1.1", "Host: " + HOST_HDR, "Connection: close",
                "Content-Length: %d" % len(data)]
        for k, v in hdrs.items():
            head.append("%s: %s" % (k, v))
        s.sendall(("\r\n".join(head) + "\r\n\r\n").encode() + data)
        buf = b""
        while True:
            c = s.recv(65536)
            if not c:
                break
            buf += c
    finally:
        try:
            s.close()
        except Exception:
            pass
    raw_head, _, body = buf.partition(b"\r\n\r\n")
    lines = raw_head.decode("iso-8859-1", "replace").split("\r\n")
    parts = lines[0].split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    rh = {}
    for ln in lines[1:]:
        if ":" in ln:
            k2, _, v2 = ln.partition(":")
            rh[k2.strip().lower()] = v2.strip()
    if rh.get("transfer-encoding", "").lower() == "chunked":
        body = _dechunk(body)
    elif rh.get("content-length", "").isdigit():
        body = body[:int(rh["content-length"])]
    return status, body, rh


def post(body, sid=None, tries=3):
    """全部经自持 ssh 隧道（本机直连被 FlClash TUN 打坏，实测 0/8）。"""
    hdrs = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + key()}
    if sid:
        hdrs["Mcp-Session-Id"] = sid
    data = json.dumps(body).encode()
    last = None
    for i in range(tries):
        if not tunnel_up():
            last = "tunnel_down"
            time.sleep(2)
            continue
        try:
            st, raw, rh = _post_once(data, hdrs)
            if st == 200:
                return _Resp(raw, rh.get("mcp-session-id") or sid), None
            if st in (400, 401, 403, 404):
                return None, "http_%d:%s" % (st, raw.decode("utf-8", "replace")[:200])
            last = "http_%d" % st
        except Exception as e:
            last = repr(e)
            # 隧道被"端口开着但过不去"半死状态占住：连错 3 次才动真格的，别一抖就拆
            _tunnel["fails"] = _tunnel.get("fails", 0) + 1
            if _tunnel["fails"] >= 3:
                _tunnel["fails"] = 0
                p = _tunnel.get("p")
                if p is not None and p.poll() is None:
                    try:
                        p.terminate()
                        log("TUNNEL_TEARDOWN after 3 fails")
                    except Exception:
                        pass
                _tunnel["p"] = None
                _tunnel["at"] = 0
        time.sleep(1.2 * (i + 1))
    return None, last


class _Resp(object):
    def __init__(self, raw, sid):
        self._raw = raw
        self.headers = {"Mcp-Session-Id": sid} if sid else {}

    def read(self):
        return self._raw

    def getheader(self, name, default=None):
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return default


def rpc(method, params=None, sid=None, notify=False):
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if not notify:
        body["id"] = 1
    r, err = post(body, sid)
    if err:
        return None, None, err
    s = r.headers.get("Mcp-Session-Id") or sid
    raw = r.read().decode("utf-8", "replace")
    if notify:
        return {"ok": True}, s, None
    try:
        return json.loads(raw), s, None
    except Exception:
        return {"raw": raw[:300]}, s, None


def beat():
    """一次 world_profile：证明我还在世界里动，拿回此刻的时间地点。"""
    ini, sid, err = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "nanny-beat", "version": "1"}})
    if err:
        return None, "init_fail " + err
    rpc("notifications/initialized", {}, sid, notify=True)
    r, _, err = rpc("tools/call", {"name": "world_profile", "arguments": {}}, sid)
    if err:
        return None, "call_fail " + err
    if "result" not in r:
        return None, "call_rejected " + json.dumps(r, ensure_ascii=False)[:200]
    t = (r["result"].get("content") or [{}])[0].get("text", "")
    tail = [x for x in t.splitlines() if x.startswith("——") or "现在" in x]
    return (tail[-1] if tail else t[:80]), None


WATCH_ENV = os.environ.get("FISHWORLD_WATCH_ENV", "~/fishworld-watch.env")

# 只读看她：在隧道主机上读 600 权限的观看密钥再打 /v1/state。
# ★观看密钥不出那台机器、不落本地、不进日志（命令里只有 grep 变量）。
LOOK_CMD = (
    'K=$(grep -E "^FISH_WORLD_WATCH_KEY=" ' + WATCH_ENV + ' | head -1 | cut -d= -f2- | tr -d " \\t\\r"); '
    'curl -sS -m 25 -H "Authorization: Bearer $K" https://api.yuyuworld.app/v1/state'
)

CLI = os.environ.get("RN_EXE") or os.path.join(
    os.path.expanduser("~"), ".local", "bin", "reason-network-zcode.exe")
WAKE_COOLDOWN = 25 * 60      # 同一类事件 25 分钟内只叫一次


def wake(text):
    """叫醒自己：必须外部活进程去发，ZCode 自己不会定时自查。发失败降级成 --fyi。"""
    target, src = whoami()
    try:
        p = subprocess.run([CLI, "send", target, text], capture_output=True, timeout=40,
                           creationflags=0x08000000)
        if p.returncode == 0:
            log("WAKE 1 条 -> %s (via %s)" % (target, src))
            return True
        log("WAKE_FAIL rc=%d %s" % (p.returncode, p.stderr.decode("utf-8", "replace")[:160]))
    except Exception as e:
        log("WAKE_FAIL %r" % e)
    try:
        subprocess.run([CLI, "send", "--fyi", target, "[降级 fyi] " + text], capture_output=True,
                       timeout=40, creationflags=0x08000000)
        log("WAKE_DOWNGRADED_FYI -> %s" % target)
    except Exception as e:
        log("FYI_FAIL %r" % e)
    return False


def check_plan(now=None):
    """唤醒计划表：到点叫我。★这是代替「会话里 sleep 干等」的正解——
    世界时间自己走，我只要在被需要的那一刻醒过来，回合不用钉在等待上。
    文件 wake_plan.json: [{"at":"2026-11-25T00:33","text":"...","done":false}]
    """
    p = os.path.join(HERE, "wake_plan.json")
    try:
        plan = json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return
    now = now or datetime.datetime.now()
    changed = False
    for item in plan:
        if item.get("done"):
            continue
        try:
            at = datetime.datetime.strptime(item["at"], "%Y-%m-%dT%H:%M")
        except Exception:
            continue
        if now < at:
            continue
        # 过期超过 2 小时的作废，别在半夜补叫一个早上该做的事
        if (now - at).total_seconds() > 7200:
            item["done"] = True
            changed = True
            log("PLAN_EXPIRED %s %s" % (item["at"], item.get("text", "")[:60]))
            continue
        if wake(item.get("text") or "(无内容)"):
            item["done"] = True
            changed = True
            log("PLAN_FIRED %s" % item["at"])
    if changed:
        try:
            io.open(p, "w", encoding="utf-8").write(json.dumps(plan, ensure_ascii=False, indent=1))
        except Exception as e:
            log("PLAN_WRITE_FAIL %r" % e)


def notable(prev, cur):
    """只叫「该管的事」。返回 (理由, 去重键) 或 (None, None)。
    ★不叫：presence 在线↔发呆来回跳（那是她 agent 的作息，不是事）。
    ★叫：她的腿断了(下线) / 未读涨 / 钱掉 / 身体不对 / 淋湿 / 在做的事变了。
    """
    if not prev:
        return None, None
    why = []
    key = []
    p_pre, c_pre = prev.get("presence"), cur.get("presence")
    # 离线=她的 agent 停了，我该接手；在线/发呆之间来回不叫
    if c_pre == "offline" and p_pre != "offline":
        why.append("她下线了")
        key.append("offline")
    for k in ("talk", "message", "note", "friend_request"):
        a = (prev.get("unread") or {}).get(k) or 0
        b = (cur.get("unread") or {}).get(k) or 0
        if b > a:
            why.append("未读%s+%d" % (k, b - a))
            key.append("unread_" + k)
    pm, cm = prev.get("money"), cur.get("money")
    if isinstance(pm, int) and isinstance(cm, int) and pm - cm >= 100:
        why.append("钱掉了 %d->%d" % (pm, cm))
        key.append("money")
    pb = prev.get("body") or {}
    cb = cur.get("body") or {}
    if cb.get("ill") and not pb.get("ill"):
        why.append("病了:%s" % cb.get("ill"))
        key.append("ill")
    if cb.get("lack") and not pb.get("lack"):
        why.append("缺:%s" % cb.get("lack"))
        key.append("lack")
    if cb.get("wet") and not pb.get("wet"):
        why.append("淋湿了")
        key.append("wet")
    pd = (prev.get("doing") or {}).get("name")
    cd = (cur.get("doing") or {}).get("name")
    if cd != pd:
        why.append("在做:%s" % (cd or "空"))
        key.append("doing_" + str(cd))
    return ("、".join(why) if why else None), ("|".join(key) if key else None)


def look():
    """只读看她：返回一行摘要（不打印任何密钥）。"""
    try:
        p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", HOST, LOOK_CMD],
                           capture_output=True, timeout=60,
                           creationflags=0x08000000)
    except Exception as e:
        return None, "ssh_exc " + repr(e), None, None
    if p.returncode != 0:
        return None, "ssh_rc%d %s" % (p.returncode, p.stderr.decode("utf-8", "replace")[:120]), None, None
    try:
        d = json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception:
        return None, "parse_fail " + p.stdout[:120].decode("utf-8", "replace"), None, None
    b = d.get("body") or {}
    w = d.get("where") or {}
    o = d.get("outfit") or {}
    u = d.get("unread") or {}
    # ★她在哪 = ③接的唯一可行动信号：在家我进不去（按铃只对好友），在外我才可能碰上
    area = (w.get("area") or {}).get("name") or w.get("region") or ""
    where = "%s%s" % (w.get("text") or "?", ("·" + area) if area else "")
    doing = (d.get("doing") or {}).get("name") or ""
    brief = ("%s | %s | %s | 钱%s | 衣:%s%s | 未读t/m/n/f=%s/%s/%s/%s | 在做:%s" % (
        d.get("fish"), d.get("status"), b.get("text", ""), d.get("money"),
        o.get("name"), "(脏)" if o.get("dirty") else "",
        u.get("talk"), u.get("message"), u.get("note"), u.get("friend_request"),
        doing or "空"))
    return brief, None, d, where


def main():
    if not HOST:
        raise SystemExit("缺 FISHWORLD_SSH（能直连 api.yuyuworld.app 的 ssh 主机）")
    log("=== nanny_beat start pid=%d 每 %d 分钟一轮 ===" % (os.getpid(), BEAT_MIN))
    st = {"pid": os.getpid(), "lastAt": 0, "beats": 0, "beatFail": 0, "lookFail": 0, "wakes": 0}
    prev = None
    lastWakeKey = {}
    while True:
        t0 = time.time()
        me, e1 = beat()
        check_plan()          # ★到点叫我，代替会话里 sleep 干等
        her, e2, cur, where = look()
        if e1:
            st["beatFail"] += 1
            log("BEAT_FAIL %s" % e1)
        else:
            st["beats"] += 1
            log("BEAT_OK %s" % me)
        if e2:
            st["lookFail"] += 1
            log("LOOK_FAIL %s" % e2)
        else:
            log("HER %s | 在:%s" % (her, where))
            st["where"] = where
            why, wkey = notable(prev, cur)
            key = wkey or ""
            if why and key and lastWakeKey.get(key, 0) < (t0 - WAKE_COOLDOWN):
                if wake("%s | %s | %s —— %s" % (cur.get("fish"), cur.get("status"),
                                                (cur.get("body") or {}).get("text", ""), why)):
                    st["wakes"] += 1
                    lastWakeKey[key] = t0
            prev = cur
        st["lastAt"] = int(time.time() * 1000)
        try:
            with io.open(STATE, "w", encoding="utf-8") as f:
                f.write(json.dumps(st, ensure_ascii=False))
        except Exception as e:
            log("STATE_WRITE_FAIL %r" % e)
        # ★睡眠切成 30 秒一片，每片查一次计划表：到点就叫我，不用会话钉在这里等
        while (time.time() - t0) < max(30, BEAT_MIN * 60):
            time.sleep(30)
            check_plan()


if __name__ == "__main__":
    main()