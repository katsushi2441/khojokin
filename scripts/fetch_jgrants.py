#!/usr/bin/env python3
"""jGrants の公開APIから補助金を取り込んで、手元の SQLite に貯める。

**画面からAPIを叩かない。** 規約の禁止事項に「短時間における大量アクセス」があり、
本機能はベータ版で予告なく止まる（第7条2）。取り込んだものを手元に持ち、
APIが落ちていても画面は出るようにする。

**公募要領・交付要綱の本文は取らない。** 第三者が著作権を持つコンテンツなので
（API利用規約 第5条2）、リンクだけを持つ。

出典: Jグランツ（https://www.jgrants-portal.go.jp）

    python3 scripts/fetch_jgrants.py                 # 受付中を全部
    python3 scripts/fetch_jgrants.py --area 愛知県
    python3 scripts/fetch_jgrants.py --all           # 受付終了も含める
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("KHOJO_DB", os.path.join(ROOT, "data", "hojokin.sqlite"))
BASE = "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies"
UA = "khojokin/0.1 (+https://exbridge.jp/)"

# 上限は 10回/1秒（API利用概要）。その1/5以下に抑える。
# 相手は国のベータ版で、こちらが急ぐ理由は何も無い。
WAIT = float(os.environ.get("KHOJO_WAIT", "0.5"))

# 一覧APIは keyword が必須。広く拾うため、よく使われる語を順に投げて束ねる。
# **語を増やすほど網羅できるが、その分リクエストが増える。** 日次で回す前提の数に抑えた。
KEYWORDS = [
    "補助金", "助成金", "支援", "中小企業", "小規模事業者", "設備", "IT", "デジタル",
    "省エネ", "脱炭素", "人材", "雇用", "創業", "販路", "事業承継", "観光", "農業",
]


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    # レンタルサーバーに置くことがあるので WAL は使わない
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("""CREATE TABLE IF NOT EXISTS subsidy(
        id TEXT PRIMARY KEY,
        name TEXT, title TEXT, catch_phrase TEXT,
        use_purpose TEXT, industry TEXT,
        target_area TEXT, target_area_detail TEXT,
        target_employees TEXT,
        subsidy_rate TEXT, max_limit INTEGER,
        acceptance_start TEXT, acceptance_end TEXT,
        project_end TEXT, official_url TEXT,
        detail_len INTEGER,
        fetched_at TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_area ON subsidy(target_area)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_end ON subsidy(acceptance_end)")
    con.execute("""CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)""")
    return con


def get(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def list_ids(keyword: str, area: str = "", acceptance: str = "1") -> list[dict]:
    q = {"keyword": keyword, "sort": "acceptance_end_datetime", "order": "ASC",
         "acceptance": acceptance}
    if area:
        q["target_area_search"] = area
    try:
        d = get(BASE + "?" + urllib.parse.urlencode(q))
    except Exception as e:  # noqa: BLE001
        print(f"    一覧が取れず（{keyword}）: {str(e)[:80]}", file=sys.stderr)
        return []
    return d.get("result") or []


def detail(sid: str):
    try:
        d = get(f"{BASE}/id/{sid}")
    except Exception as e:  # noqa: BLE001
        print(f"    詳細が取れず（{sid}）: {str(e)[:80]}", file=sys.stderr)
        return None
    r = d.get("result") or []
    return r[0] if r else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="", help="例: 愛知県")
    ap.add_argument("--all", action="store_true", help="受付終了も含める")
    ap.add_argument("--keywords", nargs="*", help="拾う語を差し替える")
    a = ap.parse_args()

    con = db()
    acc = "0" if a.all else "1"
    words = a.keywords or KEYWORDS

    seen: dict[str, dict] = {}
    for w in words:
        rows = list_ids(w, a.area, acc)
        new = sum(1 for r in rows if r["id"] not in seen)
        for r in rows:
            seen.setdefault(r["id"], r)
        print(f"  {w:12} {len(rows):4}件（うち新規 {new:4}）")
        time.sleep(WAIT)

    print(f"\n重複を除いて {len(seen)}件。詳細を取ります。")
    now = dt.datetime.now().isoformat(timespec="seconds")
    got = skipped = 0
    for i, sid in enumerate(seen, 1):
        have = con.execute("SELECT fetched_at FROM subsidy WHERE id=?", (sid,)).fetchone()
        if have and have[0][:10] == now[:10]:
            skipped += 1
            continue
        d = detail(sid)
        time.sleep(WAIT)
        if not d:
            continue
        con.execute("""INSERT OR REPLACE INTO subsidy VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            d.get("id"), d.get("name"), d.get("title"), d.get("subsidy_catch_phrase"),
            d.get("use_purpose"), d.get("industry"),
            d.get("target_area_search"), d.get("target_area_detail"),
            d.get("target_number_of_employees"),
            d.get("subsidy_rate"), d.get("subsidy_max_limit"),
            d.get("acceptance_start_datetime"), d.get("acceptance_end_datetime"),
            d.get("project_end_deadline"), d.get("front_subsidy_detail_page_url"),
            # 本文は持たない（第三者著作物）。長さだけ記録して、取りこぼしを見分ける
            len(d.get("detail") or ""), now))
        got += 1
        if i % 25 == 0:
            con.commit()
            print(f"    {i}/{len(seen)} …")
    con.execute("INSERT OR REPLACE INTO meta VALUES('updated_at',?)", (now,))
    con.execute("INSERT OR REPLACE INTO meta VALUES('source',?)",
                ("Jグランツ（https://www.jgrants-portal.go.jp）",))
    con.commit()

    tot = con.execute("SELECT COUNT(*) FROM subsidy").fetchone()[0]
    print(f"\n取得 {got}件 / 今日すでに取得済みで飛ばした {skipped}件 / 収録 {tot}件")
    print(f"DB: {DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
