#!/usr/bin/env python3
"""自治体が独自に公募していて jGrants に載らない補助金を、手書きのJSONから取り込む。

**名古屋市はjGrantsを使っていない。** 自前のオンライン申請システムで公募するため、
公開APIには1件も載らない（2026-09-15 に受付終了分を含めて0件を実測）。
それで名古屋の会社が「うちの市には補助金がない」と誤解するのは、この道具の落ち度である。

**出典はjGrantsと混ぜない。** 規約が求める出典表示はjGrantsのデータに対するもので、
市の公式ページから書き起こしたものに「出典：Jグランツ」と付けたら嘘になる。
`source` 列で分け、画面もそれぞれの出典を出す。

    python3 scripts/load_local.py data/local_nagoya.json
"""
import datetime
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("KHOJO_DB", os.path.join(ROOT, "data", "hojokin.sqlite"))


def main() -> int:
    files = sys.argv[1:] or [os.path.join(ROOT, "data", "local_nagoya.json")]
    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=5000")
    cols = {r[1] for r in con.execute("PRAGMA table_info(subsidy)")}
    # 出典が違うものを同じ表に入れるので、どこから来たかを列で持つ
    if "source" not in cols:
        con.execute("ALTER TABLE subsidy ADD COLUMN source TEXT")
        con.execute("ALTER TABLE subsidy ADD COLUMN source_url TEXT")
        con.execute("ALTER TABLE subsidy ADD COLUMN source_updated TEXT")
        con.execute("ALTER TABLE subsidy ADD COLUMN note TEXT")
        con.execute("UPDATE subsidy SET source='jgrants' WHERE source IS NULL")
        print("  source 列を足しました（既存はすべて jgrants）")

    now = datetime.datetime.now().isoformat(timespec="seconds")
    total = 0
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        for s in d["subsidies"]:
            con.execute("""INSERT OR REPLACE INTO subsidy
                (id, name, title, catch_phrase, use_purpose, industry,
                 target_area, target_area_detail, target_employees,
                 subsidy_rate, max_limit, acceptance_start, acceptance_end,
                 project_end, official_url, detail_len, fetched_at,
                 source, source_url, source_updated, note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                s["id"], s["id"], s["title"], "",
                s.get("use_purpose", ""), s.get("industry", ""),
                s.get("target_area", ""), s.get("target_area_detail", ""),
                s.get("target_employees", ""),
                s.get("subsidy_rate", ""), s.get("max_limit") or 0,
                s.get("acceptance_start", ""), s.get("acceptance_end", ""),
                "", s.get("official_url", ""), 0, now,
                d.get("source", "自治体公式"), d.get("source_url", ""),
                s.get("source_updated", ""), s.get("note", "")))
            total += 1
        print(f"  {d.get('region', f)}: {len(d['subsidies'])}件（出典: {d.get('source')}）")
    con.execute("INSERT OR REPLACE INTO meta VALUES('local_loaded_at',?)", (now,))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM subsidy").fetchone()[0]
    print(f"\n取り込み {total}件 / 収録 {n}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
