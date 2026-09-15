"""Kurage 補助金ナビ（khojokin）— 会社の条件 → 今日出せる補助金＋補助率・上限・締切・公式リンク。

  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 18360

- データは jGrants の公開APIから取り込んだ手元の SQLite（data/hojokin.sqlite）。
  **画面からAPIを叩かない。** 規約が大量アクセスを禁じ、本機能はベータ版で予告なく止まるため。
- 絞り込みは Python の条件一致だけ。**LLM は使わない。**
  補助率・上限・締切は生成してよい種類の情報ではない（規約 第5条5四ハ「事実に反する内容」）。
- 公募要領の本文は持たない（第三者著作物）。リンクだけを出す。

出典: Jグランツ（https://www.jgrants-portal.go.jp）
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.environ.get("KHOJO_DB", os.path.join(ROOT, "data", "hojokin.sqlite"))
PUBLIC_BASE = os.environ.get("KHOJO_PUBLIC_BASE", "http://127.0.0.1:18360/").rstrip("/") + "/"
SITE = "Kurage 補助金ナビ"
VERSION = "0.1.0"

# API利用規約 第5条1 が求める表示。**加工して出しているので、出典だけでは足りない。**
# **市の公式ページから書き起こしたものに、この表示を付けてはいけない。** 嘘になる。
SOURCE = "出典：Jグランツ"
MADE_BY = ("このコンテンツは、政府公式の補助金申請システム jGrants の Web-API 機能を利用して"
           "取得した情報をもとに株式会社エクスブリッジにて作成されたものです。"
           "コンテンツの内容は日本国政府及び自治体によって保証されたものではありません。")

app = FastAPI(title=SITE, version=VERSION, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))


def db():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    return con


def root_prefix(request: Request) -> str:
    """プロキシ配下（/khojokin.php/…）でも相対パスで動かすため。"""
    segs = [s for s in request.url.path.split("/") if s]
    return "../" * max(0, len(segs) - 1)


def meta(k: str) -> str:
    try:
        with db() as c:
            r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
            return r[0] if r else ""
    except sqlite3.Error:
        return ""


def _split(v: str) -> list[str]:
    """jGrants の複数値は「A / B / C」の形で入っている。"""
    return [x.strip() for x in re.split(r"[/、,]", v or "") if x.strip()]


def areas() -> list[str]:
    """選ばせる都道府県。「全国」を先頭に置く。"""
    out: set[str] = set()
    with db() as c:
        for (v,) in c.execute("SELECT DISTINCT target_area FROM subsidy WHERE target_area<>''"):
            out.update(_split(v))
    pref = sorted(x for x in out if x.endswith(("都", "道", "府", "県")))
    return (["全国"] if "全国" in out else []) + pref


def industries() -> list[str]:
    out: set[str] = set()
    with db() as c:
        for (v,) in c.execute("SELECT DISTINCT industry FROM subsidy WHERE industry<>''"):
            out.update(_split(v))
    return sorted(out)


def purposes() -> list[str]:
    out: set[str] = set()
    with db() as c:
        for (v,) in c.execute("SELECT DISTINCT use_purpose FROM subsidy WHERE use_purpose<>''"):
            out.update(_split(v))
    return sorted(out)


EMP_ORDER = ["5名以下", "20名以下", "50名以下", "100名以下", "300名以下", "従業員数の制約なし"]


def _emp_cap(v: str) -> int:
    """「300名以下」→300。制約なしは大きい数。**書いてある以上の判断はしない。**"""
    if not v or "制約なし" in v:
        return 10 ** 9
    m = re.search(r"(\d+)", v)
    return int(m.group(1)) if m else 10 ** 9


def search(area: str = "", industry: str = "", purpose: str = "",
           employees: str = "", open_only: bool = True) -> list[dict]:
    today = dt.date.today().isoformat()
    rows = []
    with db() as c:
        for r in c.execute("SELECT * FROM subsidy"):
            d = dict(r)
            if open_only:
                end = (d.get("acceptance_end") or "")[:10]
                start = (d.get("acceptance_start") or "")[:10]
                if end and end < today:
                    continue
                # 通年・随時の制度は受付開始日を書いていないことがある。
                # 開始日だけで落とすと「年度内いつでも」の市の制度が消える
                if start and end and start > today:
                    continue
            if area:
                a = _split(d.get("target_area") or "")
                if area not in a and "全国" not in a:
                    continue
            if industry:
                ind = _split(d.get("industry") or "")
                if ind and industry not in ind:
                    continue
            if purpose:
                p = _split(d.get("use_purpose") or "")
                if p and purpose not in p:
                    continue
            if employees:
                # 自社の人数が、その補助金の上限以下なら対象になりうる
                if _emp_cap(d.get("target_employees") or "") < _emp_cap(employees):
                    continue
            d["days_left"] = _days_left(d.get("acceptance_end"))
            d["area_label"] = area_label(d.get("target_area") or "")
            d["is_local_gov"] = (d.get("source") or "jgrants") != "jgrants"
            # 地域を選んだ人が見たいのは、まず地元のもの。
            # 全国のものも対象ではあるが、それだけで画面が埋まると地元が見えない。
            _a = _split(d.get("target_area") or "")
            # **全国のものは「地元」にしない。** 全国の公募は対象地域に全都道府県を
            # 並べてくるので、素直に突き合わせると全部が地元になってしまう。
            d["local"] = bool(area) and area in _a and not _is_nationwide(_a)
            rows.append(d)
    rows.sort(key=lambda x: (not x["local"], x["days_left"] is None,
                             x["days_left"] if x["days_left"] is not None else 0))
    return rows


# 「全国」と書かず47都道府県を並べてくる公募がある。実質は全国なので同じ扱いにする。
NATIONWIDE_MIN = 40


def _is_nationwide(a: list[str]) -> bool:
    return "全国" in a or len(a) >= NATIONWIDE_MIN


def area_label(v: str) -> str:
    """対象地域を短く見せる。全国のものは都道府県を全部並べてくるので丸める。"""
    a = _split(v)
    if not a:
        return ""
    if _is_nationwide(a):
        return "全国"
    if len(a) <= 3:
        return "・".join(a)
    return "・".join(a[:3]) + f" ほか{len(a) - 3}"


def _days_left(end: str | None):
    if not end:
        return None
    try:
        d = dt.date.fromisoformat(end[:10])
    except ValueError:
        return None
    return (d - dt.date.today()).days


def jsonld(extra: dict | None = None) -> str:
    """AI検索と検索エンジンに、何のサイトで出典がどこかを機械可読で渡す。"""
    d = {"@context": "https://schema.org", "@type": "WebSite", "name": SITE,
         "url": PUBLIC_BASE, "inLanguage": "ja",
         "publisher": {"@type": "Organization", "name": "株式会社エクスブリッジ",
                       "url": "https://exbridge.jp/"},
         "isBasedOn": {"@type": "Dataset", "name": "Jグランツ 補助金情報",
                       "url": "https://www.jgrants-portal.go.jp"}}
    if extra:
        d.update(extra)
    return json.dumps(d, ensure_ascii=False)


def ctx(request: Request, **kw):
    base = {"request": request, "site": SITE, "rp": root_prefix(request),
            "source": SOURCE, "made_by": MADE_BY, "public_base": PUBLIC_BASE,
            "show_jgrants": True,
            "jsonld": kw.pop("jsonld", None) or jsonld(),
            "updated_at": meta("updated_at")[:10], "version": VERSION}
    base.update(kw)
    return base


@app.get("/", response_class=HTMLResponse)
def index(request: Request, area: str = "", industry: str = "", purpose: str = "",
          employees: str = "", show_closed: str = ""):
    picked = any([area, industry, purpose, employees])
    rows = search(area, industry, purpose, employees, open_only=not show_closed) if picked else []
    with db() as c:
        total = c.execute("SELECT COUNT(*) FROM subsidy").fetchone()[0]
        open_n = len(search(open_only=True))
    return templates.TemplateResponse(request, "index.html", ctx(
        request, rows=rows, picked=picked, total=total, open_n=open_n,
        areas=areas(), industries=industries(), purposes=purposes(), emps=EMP_ORDER,
        sel={"area": area, "industry": industry, "purpose": purpose,
             "employees": employees, "show_closed": show_closed}))


@app.get("/s/{sid}", response_class=HTMLResponse)
def show(request: Request, sid: str):  # noqa: D103
    with db() as c:
        r = c.execute("SELECT * FROM subsidy WHERE id=?", (sid,)).fetchone()
    if not r:
        return HTMLResponse("<h1>その補助金は収録していません</h1>", status_code=404)
    d = dict(r)
    d["days_left"] = _days_left(d.get("acceptance_end"))
    d["is_local_gov"] = (d.get("source") or "jgrants") != "jgrants"
    ld = jsonld({"@type": "GovernmentService", "name": d.get("title"),
                 "url": PUBLIC_BASE + "s/" + sid,
                 "serviceType": "補助金",
                 "provider": {"@type": "GovernmentOrganization",
                              "name": d.get("target_area_detail") or "Jグランツ掲載機関"},
                 "areaServed": _split(d.get("target_area") or "")[:5],
                 "isBasedOn": {"@type": "Dataset",
                               "name": (d.get("source") or "Jグランツ 補助金情報"),
                               "url": d.get("source_url") or d.get("official_url")
                                      or "https://www.jgrants-portal.go.jp"}})
    return templates.TemplateResponse(request, "detail.html", ctx(
        request, jsonld=ld, s=d, show_jgrants=not d["is_local_gov"],
        industry_list=_split(d.get("industry") or ""),
        purpose_list=_split(d.get("use_purpose") or ""),
        area_list=_split(d.get("target_area") or "")))


@app.get("/about", response_class=HTMLResponse)
def about(request: Request):
    with db() as c:
        total = c.execute("SELECT COUNT(*) FROM subsidy").fetchone()[0]
    return templates.TemplateResponse(request, "about.html", ctx(request, total=total, open_n=len(search())))


@app.get("/api/subsidies")
def api(area: str = "", industry: str = "", purpose: str = "", employees: str = ""):
    rows = search(area, industry, purpose, employees)
    return JSONResponse({"source": SOURCE, "notice": MADE_BY,
                         "updated_at": meta("updated_at"), "count": len(rows), "items": rows})


@app.get("/health")
def health():
    try:
        with db() as c:
            n = c.execute("SELECT COUNT(*) FROM subsidy").fetchone()[0]
        return {"ok": True, "subsidies": n, "updated_at": meta("updated_at")}
    except sqlite3.Error as e:
        return JSONResponse({"ok": False, "error": str(e)[:120]}, status_code=503)


@app.get("/sitemap.xml")
def sitemap():
    today = dt.date.today().isoformat()
    urls = [PUBLIC_BASE, PUBLIC_BASE + "about"]
    with db() as c:
        # 受付中のものだけ載せる。終わった公募を検索結果に残しても誰の役にも立たない
        rows = c.execute("SELECT id FROM subsidy WHERE acceptance_end >= ? OR acceptance_end IS NULL"
                         " OR acceptance_end=''", (today,)).fetchall()
    urls += [PUBLIC_BASE + f"s/{r[0]}" for r in rows]
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls)
            + "</urlset>\n")
    return Response(content=body, media_type="application/xml")


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms():
    with db() as c:
        n = c.execute("SELECT COUNT(*) FROM subsidy").fetchone()[0]
    return "\n".join([
        f"# {SITE}", "",
        "> 会社の地域・業種・従業員数・やりたいことから、いま応募できる補助金と、"
        "補助率・上限額・締切・公式ページを引くサイト。",
        "",
        f"- 収録: {n}件（取り込み {meta('updated_at')[:10]}）",
        "- 出典: Jグランツ（デジタル庁・https://www.jgrants-portal.go.jp）の公開API",
        f"- API: {PUBLIC_BASE}api/subsidies?area=愛知県&industry=製造業&employees=20名以下",
        f"- 補助金ページ: {PUBLIC_BASE}s/<id>",
        "",
        "## この道具が答えられること",
        "- ある地域・業種・従業員規模の会社が、今日応募できる補助金はどれか",
        "- その補助金の補助率・上限額・受付期間・対象地域・対象業種",
        "",
        "## 答えられないこと",
        "- 応募の可否（要件は公募要領次第。このサイトは要領の本文を持っていません）",
        "- 申請書類の作成（様式は補助金ごとに違い、中身は事業計画そのものです）",
        "- 厚生労働省の雇用関係助成金の大半（Jグランツに載っているものだけです）",
        "",
        f"個人向けの制度: https://kurage.exbridge.jp/kseido.php/",
    ]) + "\n"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return f"User-agent: *\nAllow: /\nSitemap: {PUBLIC_BASE}sitemap.xml\n"
