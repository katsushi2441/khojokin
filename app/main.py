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
import os
import re
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.environ.get("KHOJO_DB", os.path.join(ROOT, "data", "hojokin.sqlite"))
PUBLIC_BASE = os.environ.get("KHOJO_PUBLIC_BASE", "http://127.0.0.1:18360/").rstrip("/") + "/"
SITE = "Kurage 補助金ナビ"
VERSION = "0.1.0"

# API利用規約 第5条1 が求める表示。**加工して出しているので、出典だけでは足りない。**
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
                if start and start > today:
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


def ctx(request: Request, **kw):
    base = {"request": request, "site": SITE, "rp": root_prefix(request),
            "source": SOURCE, "made_by": MADE_BY,
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
def show(request: Request, sid: str):
    with db() as c:
        r = c.execute("SELECT * FROM subsidy WHERE id=?", (sid,)).fetchone()
    if not r:
        return HTMLResponse("<h1>その補助金は収録していません</h1>", status_code=404)
    d = dict(r)
    d["days_left"] = _days_left(d.get("acceptance_end"))
    return templates.TemplateResponse(request, "detail.html", ctx(
        request, s=d, industry_list=_split(d.get("industry") or ""),
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


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return f"User-agent: *\nAllow: /\nSitemap: {PUBLIC_BASE}sitemap.xml\n"
