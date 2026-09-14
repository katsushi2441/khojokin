#!/usr/bin/env python3
"""kdeck から呼ばれる日次の入口。jGrantsから取り込み直して、画面が読むDBを入れ替える。

**取り込みに失敗したら、古いDBをそのまま残す。** 相手はベータ版で予告なく止まるので
（API利用規約 第7条2）、落ちた日に画面が空になるほうが困る。
"""
import datetime
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.environ.get("KHOJO_PYTHON", "/usr/bin/python3")


def _counts():
    import sqlite3
    db = os.path.join(ROOT, "data", "hojokin.sqlite")
    if not os.path.isfile(db):
        return {"subsidy": 0, "updated_at": ""}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM subsidy").fetchone()[0]
    r = con.execute("SELECT v FROM meta WHERE k='updated_at'").fetchone()
    con.close()
    return {"subsidy": n, "updated_at": r[0] if r else ""}


def update_hojokin_job(**_) -> dict:
    started = datetime.datetime.now().isoformat(timespec="seconds")
    before = _counts()
    r = subprocess.run([PY, os.path.join(ROOT, "scripts", "fetch_jgrants.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=3600)
    after = _counts()
    ok = r.returncode == 0 and after["subsidy"] >= before["subsidy"]
    return {
        "ok": ok, "items": 1 if ok else 0,
        "started": started, "finished": datetime.datetime.now().isoformat(timespec="seconds"),
        "before": before, "after": after,
        "tail": (r.stdout or "").strip().splitlines()[-5:],
        "err": (r.stderr or "").strip().splitlines()[-3:] if r.returncode else [],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(update_hojokin_job(), ensure_ascii=False, indent=1))
