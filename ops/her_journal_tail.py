# -*- coding: utf-8 -*-
"""读她 journal 尾部，打印 turn 里的 user/assistant 内容（用于判"叫醒了有没有真干活"）。"""
import json, io, datetime, sys, subprocess, os

SESS = os.environ.get("FISHWORLD_SESSION_JSONL", "")   # ← 必填：她那边的会话 jsonl.zstd 路径
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60

def decompress(path, n):
    # zstd -dc 流式解，取尾部 n 行
    p = subprocess.run(["zstd", "-dc", path], capture_output=True)
    raw = p.stdout.decode("utf-8", "replace")
    lines = [l for l in raw.split("\n") if l.strip()]
    return lines[-n:]

lines = decompress(SESS, N)

for ln in lines:
    try:
        d = json.loads(ln)
    except Exception:
        continue
    t = d.get("type")
    ts = d.get("time") or 0
    data = d.get("data") or {}
    when = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S") if ts else "?"
    if t in ("assistant/message", "user/message"):
        msg = data.get("message") or data
        role = msg.get("role") or ""
        c = msg.get("content")
        txt = ""
        if isinstance(c, list):
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    txt += (b.get("text") or "")
                elif b.get("type") == "tool_use":
                    txt += "[TOOL " + str(b.get("name")) + "] " + json.dumps(b.get("input"), ensure_ascii=False)[:180]
        elif isinstance(c, str):
            txt = c
        if not txt.strip():
            continue
        print("=" * 8, when, t, role)
        print(txt[:800].replace("\n", "\n  "))
    elif t in ("turn/start", "turn/end", "compaction/summary", "agent/inbox/spliced", "step/start"):
        print("--", when, t, json.dumps(data, ensure_ascii=False)[:200])