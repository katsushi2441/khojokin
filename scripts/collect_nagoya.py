#!/usr/bin/env python3
"""名古屋市の事業者向け補助金のページを洗い出す（下ごしらえ。人が確認してからJSONにする）。

**名古屋市は jGrants を使っていない。** 自前のオンライン申請システムで公募するため、
デジタル庁の公開APIには1件も載らない（2026-09-15 に受付終了分を含めて0件を実測）。
それで名古屋の会社が「うちの市には補助金がない」と誤解するのは、この道具の落ち度である。

**本文は取らない。** 名古屋市サイトの文章は転載できない。
制度名・上限額・補助率・期間・リンク・公式の更新日という「事実」だけを拾う。

    python3 scripts/collect_nagoya.py            # 候補ページを一覧にする
    python3 scripts/collect_nagoya.py --detail   # 各ページから数字も拾う
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs", "nagoya_candidates.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) khojokin/0.1"
BASE = "https://www.city.nagoya.jp"
INDEX = BASE + "/jigyou/sangyou/1026356/index.html"
WAIT = 1.0

# 補助金・助成金だけを拾う。融資・相談・専門家派遣・税制優遇は対象外
YES = re.compile(r"(補助金|助成金|奨励金|給付金|補助制度)")
NO = re.compile(r"(融資|資金繰り|保証|相談|セミナー|専門家派遣|税の特例|固定資産税|税制)")


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "ignore")


def links(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not text or href.startswith(("#", "javascript:", "mailto:")):
            continue
        out.append((text, urllib.parse.urljoin(base, href)))
    return out


def updated(html: str) -> str:
    m = re.search(r"更新日[：:\s]*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", html)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def facts(html: str) -> dict:
    """数字だけを拾う。文章は取らない。

    表（<table>）に入っていることが多いので、タグを消す前に区切りを入れる。
    区切りなしで消すと「補助限度額100万円」が隣の見出しとつながって拾えない。
    """
    txt = re.sub(r"</(td|th|tr|li|p|div|h[1-6])>", " / ", html, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"&nbsp;?", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    d = {}
    m = re.search(r"(?:補助限度額|補助上限額?|限度額|上限額|交付限度額|補助金額)\s*[：:／/]?\s*"
                  r"([0-9０-９][0-9０-９,，.．]*\s*(?:億|万|千)?\s*円)", txt)
    if m:
        d["limit_text"] = re.sub(r"\s+", "", m.group(1))
    m = re.search(r"補助率\s*[：:／/]?\s*([^/。]{2,36})", txt)
    if m:
        d["rate_text"] = m.group(1).strip()
    m = re.search(r"((?:令和|平成)\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日"
                  r"[^/。]{0,50}?(?:まで|必着|消印有効))", txt)
    if m:
        d["period_text"] = re.sub(r"\s+", "", m.group(1))
    if re.search(r"(?:募集|受付|申請)[はを]?(?:終了|締め切)|終了しました|受付を終了", txt):
        d["closed"] = True
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args()

    cats = [(t, u) for t, u in links(get(INDEX), INDEX)
            if "/jigyou/sangyou/1026356/" in u and u.endswith("/index.html") and u != INDEX]
    seen_cat = {}
    for t, u in cats:
        seen_cat.setdefault(u, t)
    print(f"カテゴリ {len(seen_cat)}件")

    found: dict[str, dict] = {}
    for u, cat in seen_cat.items():
        time.sleep(WAIT)
        try:
            html = get(u)
        except Exception as e:  # noqa: BLE001
            print(f"  取れず {cat}: {str(e)[:60]}", file=sys.stderr)
            continue
        hits = 0
        # index.html の先にもう1階層ある（「創業・新事業展開のための補助制度」など）。
        # そこで止めると個別の補助金に辿り着けない
        deeper = []
        for text, href in links(html, u):
            if not href.startswith(BASE) or "/jigyou/" not in href:
                continue
            if not YES.search(text) or NO.search(text):
                continue
            if href.endswith("/index.html"):
                if href not in seen_cat:
                    deeper.append((text, href))
                continue
            if href not in found:
                found[href] = {"name": text, "category": cat, "url": href}
                hits += 1
        for dtext, durl in deeper:
            time.sleep(WAIT)
            try:
                dhtml = get(durl)
            except Exception:  # noqa: BLE001
                continue
            for text, href in links(dhtml, durl):
                if not href.startswith(BASE) or "/jigyou/" not in href:
                    continue
                if not YES.search(text) or NO.search(text) or href.endswith("/index.html"):
                    continue
                if href not in found:
                    found[href] = {"name": text, "category": dtext, "url": href}
                    hits += 1
        print(f"  {cat:28} {hits:2}件")

    if a.detail:
        print(f"\n詳細を見ます（{len(found)}件）")
        for i, (u, rec) in enumerate(found.items(), 1):
            time.sleep(WAIT)
            try:
                html = get(u)
            except Exception:  # noqa: BLE001
                continue
            rec.update(facts(html))
            rec["source_updated"] = updated(html)
            if i % 10 == 0:
                print(f"    {i}/{len(found)} …")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(list(found.values()), open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{len(found)}件 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
