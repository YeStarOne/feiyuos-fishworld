# -*- coding: utf-8 -*-
"""act.py —— 奶妈的双手：经隧道调 fish-world 的任意工具。
复用 nanny_beat 已经验过的隧道 + 分块解码，不另写一套网络。

用法：
  python act.py now
  python act.py profile
  python act.py do '{"action":"work"}'
  python act.py say '{"text":"..."}'
  python act.py go '{"to":"tide-mart"}'
"""
import sys, os, json, atexit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nanny_beat as n

# ★act.py 是一次性短命进程：固定用 18443 这条共享口，已有就借用，
#   自己起的在退出时收掉，否则每调一次工具就留一条 ssh 孤儿。
n.LPORT = 18443


def _reap():
    p = n._tunnel.get("p")
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass


atexit.register(_reap)

# 「工具名 world_xxx」→ 真名
ALIAS = {"now": "world_now", "profile": "world_profile", "find": "world_find",
         "history": "world_history", "go": "world_go", "do": "world_do",
         "say": "world_say", "friends": "world_friends", "feed": "world_feed",
         "update": "world_update", "guide": "world_guide"}


def call(name, args=None):
    name = ALIAS.get(name, name)
    ini, sid, e = n.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "nanny-act", "version": "1"}})
    if e:
        return None, "INIT_FAIL " + e
    n.rpc("notifications/initialized", {}, sid, notify=True)
    r, _, e = n.rpc("tools/call", {"name": name, "arguments": args or {}}, sid)
    if e:
        return None, "CALL_FAIL " + e
    if "result" not in r:
        return None, "REJECT " + json.dumps(r, ensure_ascii=False)[:300]
    res = r["result"]
    txt = (res.get("content") or [{}])[0].get("text", "")
    return txt, (None if not res.get("isError") else "isError")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    name = sys.argv[1] if len(sys.argv) > 1 else "now"
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    txt, err = call(name, args)
    if err:
        print("[ERR]", err)
        if txt:
            print(txt)
        sys.exit(1)
    print(txt)