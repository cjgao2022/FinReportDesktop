"""
财报下载器 — 双数据源财务报告批量下载工具
数据来源：新浪财经 + 巨潮资讯
打包：pyinstaller --onefile --noconsole --name 财报下载器 main.py
"""
from __future__ import annotations

import html
import os
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Dict, List, Optional
from urllib.parse import quote

import requests

# ─────────────────────────── 常量 ───────────────────────────

APP_NAME = "财报下载器"
APP_VERSION = "1.0"

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REPORT_TYPES = ["年报", "一季报", "中报", "三季报", "全部"]

# ─────────────────────────── 新浪财经 ───────────────────────────

_SINA_LIST_BASE   = "https://money.finance.sina.com.cn"
_SINA_DETAIL_BASE = "https://vip.stock.finance.sina.com.cn"
_SINA_SUGGEST_URL = "https://suggest3.sinajs.cn/suggest"

_SINA_TYPE_MAP = {
    "年报":  "ndbg",
    "一季报": "yjdbg",
    "中报":  "zqbg",
    "三季报": "sjdbg",
}

_SINA_ROUTES = {
    "ndbg":  {"path": "vCB_Bulletin",       "page_type": "ndbg"},
    "yjdbg": {"path": "vCB_BulletinYi",     "page_type": "yjdbg"},
    "zqbg":  {"path": "vCB_BulletinZhong",  "page_type": "zqbg"},
    "sjdbg": {"path": "vCB_BulletinSan",    "page_type": "sjdbg"},
}


def sina_resolve_stock(query: str) -> Dict[str, str]:
    url = f"{_SINA_SUGGEST_URL}/type=11,12,13,14,15&key={quote(query)}"
    resp = requests.get(url, headers=COMMON_HEADERS, timeout=15)
    resp.encoding = "gbk"
    m = re.search(r'var\s+suggestvalue\s*=\s*"(.*?)"', resp.text)
    if m:
        payload = m.group(1).strip()
        for raw in payload.split(";"):
            if not raw:
                continue
            fields = raw.split(",")
            if len(fields) >= 4 and re.fullmatch(r"\d{6}", fields[2]):
                name = ""
                if len(fields) > 4 and fields[4].strip():
                    name = fields[4].strip()
                elif len(fields) > 6 and fields[6].strip():
                    name = fields[6].strip()
                return {
                    "stock_id":   fields[2],
                    "stock_name": name or fields[0] or fields[2],
                }
    if re.fullmatch(r"\d{6}", query):
        return {"stock_id": query, "stock_name": query}
    raise ValueError("新浪财经：未找到匹配的股票")


def _sina_fetch_one_type(stock_id: str, report_type: str) -> List[Dict]:
    route = _SINA_ROUTES.get(report_type)
    if not route:
        return []
    url = (
        f"{_SINA_LIST_BASE}/corp/go.php/{route['path']}/stockid/{stock_id}/"
        f"page_type/{route['page_type']}.phtml"
    )
    resp = requests.get(url, headers=COMMON_HEADERS, timeout=20)
    resp.encoding = "gb18030"
    m = re.search(r'<div class="datelist">(.*?)</div>', resp.text, re.S)
    if not m:
        return []
    fragment = m.group(1)
    pattern = re.compile(
        r'(\d{4}-\d{2}-\d{2})&nbsp;\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>',
        re.S,
    )
    items: List[Dict] = []
    for date_text, href, title in pattern.findall(fragment):
        detail_url = html.unescape(href)
        if detail_url.startswith("/"):
            detail_url = f"{_SINA_DETAIL_BASE}{detail_url}"
        id_m = re.search(r"(?:[?&]id=)(\d+)", detail_url)
        bulletin_id = id_m.group(1) if id_m else ""
        yr_m = re.search(r"((?:19|20)\d{2})年", title) or re.search(r"(?:19|20)\d{2}", title)
        report_year = yr_m.group(1) if yr_m else date_text[:4]
        items.append({
            "id":          bulletin_id,
            "title":       title.strip(),
            "date":        date_text,
            "detail_url":  detail_url,
            "report_year": report_year,
            "source":      "新浪财经",
            "pdf_url":     "",          # 下载时再解析
        })
    return items


def sina_fetch_reports(stock_id: str, report_type: str, year: Optional[int] = None) -> List[Dict]:
    if report_type == "全部":
        items: List[Dict] = []
        for rt in _SINA_ROUTES:
            items.extend(_sina_fetch_one_type(stock_id, rt))
        seen: set = set()
        deduped: List[Dict] = []
        for item in items:
            key = item["id"] or item["detail_url"]
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        items = deduped
    else:
        rt = _SINA_TYPE_MAP.get(report_type, "ndbg")
        items = _sina_fetch_one_type(stock_id, rt)

    items.sort(key=lambda x: x["date"], reverse=True)
    if year:
        items = [i for i in items if i.get("report_year") == str(year)]
    return items


def sina_get_pdf_url(stock_id: str, bulletin_id: str, detail_url: str) -> str:
    resp = requests.get(detail_url, headers=COMMON_HEADERS, timeout=20)
    resp.encoding = "gb18030"
    page_html = resp.text
    anchor = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]{0,30})</a>', re.I)
    for href, text in anchor.findall(page_html):
        if ("下载" in text or "PDF" in text.upper()) and (
            ".pdf" in href.lower() or "download" in href.lower()
        ):
            return _normalize_url(html.unescape(href), _SINA_DETAIL_BASE)
    m = re.search(r'href=["\']([^"\']+\.pdf)["\']', page_html, re.I)
    if m:
        return _normalize_url(html.unescape(m.group(1)), _SINA_DETAIL_BASE)
    raise ValueError("新浪财经：未找到 PDF 下载链接")


def _normalize_url(url: str, base: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"{base}{url}"
    return url


# ─────────────────────────── 巨潮资讯 ───────────────────────────

_CNINFO_BASE   = "https://www.cninfo.com.cn"
_CNINFO_STATIC = "https://static.cninfo.com.cn"

_CNINFO_HEADERS = {
    **COMMON_HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin":           "https://www.cninfo.com.cn",
    "Referer":          "https://www.cninfo.com.cn/new/index",
}

_CNINFO_CATEGORY = {
    "年报":  "category_ndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "中报":  "category_bndbg_szsh",
    "三季报": "category_sjdbg_szsh",
    "全部":  "",
}


def _derive_cninfo_meta(code: str) -> tuple:
    """从代码首位推导 column / plate（orgId 不再用推导，改为查询发现）。"""
    first = code[0]
    if first in ("6", "9"):
        return "", "sse", "sh"
    if first in ("4", "8"):
        return "", "bse", "bj"
    return "", "szse", "sz"


_STOCK_ORG_PREFIXES = ("gssz", "gssh", "gsbj", "9900")


def _cninfo_discover_orgid(stock_id: str) -> str:
    """通过关键词搜发现股票的真实 orgId。
    主板股票的 orgId 可从代码推导（gssz/gssh/gsbj + 0 + code），
    但创业板、科创板等较新上市股票使用 9900XXXXXXXX 格式，无法推导。
    过滤条件：secCode 完全匹配 + orgId 为 A 股公司合法前缀。
    """
    resp = requests.post(
        f"{_CNINFO_BASE}/new/hisAnnouncement/query",
        data={
            "stock": "", "tabName": "fulltext",
            "pageNum": 1, "pageSize": 10,
            "column": "", "category": "",
            "plate": "", "seDate": "",
            "searchkey": stock_id, "isHLtitle": "false",
        },
        headers=_CNINFO_HEADERS,
        timeout=15,
    )
    anns = resp.json().get("announcements") or []
    for ann in anns:
        org = ann.get("orgId", "")
        if ann.get("secCode") == stock_id and any(org.startswith(p) for p in _STOCK_ORG_PREFIXES):
            return org
    return ""


def _derive_fallback_orgid(code: str) -> str:
    """主板股票 orgId 推导公式（适用于 000001、600036 等老牌主板股）。"""
    first = code[0]
    if first in ("6", "9"):
        return f"gssh0{code}"
    if first in ("4", "8"):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def cninfo_resolve_stock(query: str) -> Dict[str, str]:
    if re.fullmatch(r"\d{6}", query):
        stock_id   = query
        stock_name = query
    else:
        si = sina_resolve_stock(query)
        stock_id   = si["stock_id"]
        stock_name = si["stock_name"]

    _, column, plate = _derive_cninfo_meta(stock_id)
    # 先尝试关键词搜发现 orgId（适用于创业板/科创板等 9900 前缀股票）
    # 若无结果（如 000001 被基金代码干扰），回退到主板推导公式
    org_id = _cninfo_discover_orgid(stock_id) or _derive_fallback_orgid(stock_id)
    return {
        "stock_id":   stock_id,
        "stock_name": stock_name,
        "org_id":     org_id,
        "column":     column,
        "plate":      plate,
    }


def cninfo_fetch_reports(
    stock_id: str,
    org_id: str,
    column: str,
    plate: str,
    report_type: str,
    year: Optional[int] = None,
) -> List[Dict]:
    category = _CNINFO_CATEGORY.get(report_type, "")

    # seDate 过滤的是公告发布日期，而年报 2025 发布于 2026 年，用 seDate 会漏掉。
    # 改为拉取全量后按标题里的报告年度客户端过滤，与新浪财经保持一致。

    all_items: List[Dict] = []
    page_num = 1
    while page_num <= 20:          # 最多取 20 页 × 30 条 = 600 条
        post_data = {
            "stock":      f"{stock_id},{org_id}",
            "tabName":    "fulltext",
            "pageNum":    page_num,
            "pageSize":   30,
            "column":     column or "szse",
            "category":   category,
            "plate":      plate or "",
            "seDate":     "",
            "searchkey":  "",
            "secid":      "",
            "trade":      "",
            "isHLtitle":  "true",
        }
        resp = requests.post(
            f"{_CNINFO_BASE}/new/hisAnnouncement/query",
            data=post_data,
            headers={
                **_CNINFO_HEADERS,
                "Referer": f"{_CNINFO_BASE}/new/disclosure/stock?stockCode={stock_id}&orgId={org_id}",
            },
            timeout=20,
        )
        data  = resp.json()
        announcements = data.get("announcements") or []
        for ann in announcements:
            ts = ann.get("announcementTime", 0)
            try:
                date_str = datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
            except Exception:
                date_str = str(ts)[:10]
            title     = ann.get("announcementTitle", "").strip()
            yr_m      = re.search(r"((?:19|20)\d{2})年", title) or re.search(r"(?:19|20)\d{2}", title)
            report_year = yr_m.group(1) if yr_m else date_str[:4]
            adjunct   = ann.get("adjunctUrl", "")
            # adjunctUrl 无前缀斜杠，需手动加 /
            pdf_url   = f"{_CNINFO_STATIC}/{adjunct}" if adjunct else ""
            all_items.append({
                "id":          ann.get("announcementId", ""),
                "title":       title,
                "date":        date_str,
                "detail_url":  pdf_url,
                "report_year": report_year,
                "source":      "巨潮资讯",
                "pdf_url":     pdf_url,
                "sec_name":    ann.get("secName", ""),
            })
        if not data.get("hasMore", False):
            break
        page_num += 1

    # 按标题里的报告年度过滤（seDate 过滤的是发布日期，会漏掉跨年发布的报告）
    if year:
        all_items = [i for i in all_items if i.get("report_year") == str(year)]

    return all_items


# ─────────────────────────── 下载工具 ───────────────────────────

def sanitize_filename(text: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:100] if cleaned else "report"


def download_pdf(pdf_url: str, save_path: str) -> None:
    pdf_headers = {**COMMON_HEADERS, "Referer": "https://www.cninfo.com.cn/"}
    resp = requests.get(pdf_url, headers=pdf_headers, stream=True, timeout=60)
    resp.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=128 * 1024):
            if chunk:
                f.write(chunk)


# ─────────────────────────── GUI ───────────────────────────

class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry("1060x660")
        self.minsize(800, 520)

        self._reports:    List[Dict] = []
        self._stock_info: Dict       = {}
        self._checked:    set        = set()   # tree iid 集合
        self._save_dir    = str(Path.home() / "Downloads")
        self._queue:      queue.Queue = queue.Queue()

        self._build_ui()
        self._poll()

    # ── 界面构建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Action.TLabel", foreground="#1565c0", cursor="hand2")
        style.configure("Done.TLabel",   foreground="#2e7d32")
        style.configure("Fail.TLabel",   foreground="#c62828")

        # ── 搜索区 ──
        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill=tk.X)

        ttk.Label(top, text="股票代码/名称:").grid(row=0, column=0, sticky=tk.W)
        self._query_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self._query_var, width=14)
        e.grid(row=0, column=1, padx=(4, 12))
        e.bind("<Return>", lambda _: self._do_search())

        ttk.Label(top, text="报告类型:").grid(row=0, column=2, sticky=tk.W)
        self._type_var = tk.StringVar(value="年报")
        ttk.Combobox(top, textvariable=self._type_var, values=REPORT_TYPES,
                     width=7, state="readonly").grid(row=0, column=3, padx=(4, 12))

        ttk.Label(top, text="年份:").grid(row=0, column=4, sticky=tk.W)
        cur_year = datetime.now().year
        years    = ["全部年份"] + [str(y) for y in range(cur_year, 1999, -1)]
        self._year_var = tk.StringVar(value="全部年份")
        ttk.Combobox(top, textvariable=self._year_var, values=years,
                     width=8, state="readonly").grid(row=0, column=5, padx=(4, 12))

        ttk.Label(top, text="数据源:").grid(row=0, column=6, sticky=tk.W)
        self._src_var = tk.StringVar(value="双源")
        ttk.Combobox(top, textvariable=self._src_var, values=["双源", "新浪财经", "巨潮资讯"],
                     width=8, state="readonly").grid(row=0, column=7, padx=(4, 16))

        self._search_btn = ttk.Button(top, text="查  询", command=self._do_search, width=8)
        self._search_btn.grid(row=0, column=8)

        # ── 保存目录 ──
        ttk.Label(top, text="保存目录:").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        self._dir_var = tk.StringVar(value=self._save_dir)
        ttk.Entry(top, textvariable=self._dir_var, width=60).grid(
            row=1, column=1, columnspan=7, padx=(4, 4), pady=(8, 0), sticky=tk.EW)
        ttk.Button(top, text="选择…", command=self._choose_dir).grid(row=1, column=8, pady=(8, 0))

        # ── 表格区 ──
        mid = ttk.Frame(self, padding=(12, 4, 12, 0))
        mid.pack(fill=tk.BOTH, expand=True)

        cols = ("chk", "date", "year", "title", "source", "action")
        self._tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="none")
        self._tree.heading("chk",    text="✓",     anchor=tk.CENTER)
        self._tree.heading("date",   text="日期",   anchor=tk.W)
        self._tree.heading("year",   text="报告年度", anchor=tk.CENTER)
        self._tree.heading("title",  text="报告名称", anchor=tk.W)
        self._tree.heading("source", text="来源",   anchor=tk.CENTER)
        self._tree.heading("action", text="操作",   anchor=tk.CENTER)
        self._tree.column("chk",    width=36,  stretch=False, anchor=tk.CENTER)
        self._tree.column("date",   width=96,  stretch=False, anchor=tk.W)
        self._tree.column("year",   width=70,  stretch=False, anchor=tk.CENTER)
        self._tree.column("title",  width=560, anchor=tk.W)
        self._tree.column("source", width=74,  stretch=False, anchor=tk.CENTER)
        self._tree.column("action", width=80,  stretch=False, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._tree.tag_configure("done", foreground="#2e7d32")
        self._tree.tag_configure("fail", foreground="#c62828")
        self._tree.bind("<ButtonRelease-1>", self._on_click)

        # ── 底部操作栏 ──
        bot = ttk.Frame(self, padding=(12, 6, 12, 6))
        bot.pack(fill=tk.X, side=tk.BOTTOM)

        self._all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bot, text="全选", variable=self._all_var,
                        command=self._toggle_all).pack(side=tk.LEFT)

        self._dl_btn = ttk.Button(bot, text="下载选中", state=tk.DISABLED,
                                  command=self._download_selected)
        self._dl_btn.pack(side=tk.LEFT, padx=(10, 0))

        self._progress = ttk.Progressbar(bot, mode="indeterminate", length=100)
        self._progress.pack(side=tk.LEFT, padx=(12, 0))

        self._summary_var = tk.StringVar(value="")
        ttk.Label(bot, textvariable=self._summary_var).pack(side=tk.RIGHT)

        # ── 状态栏 ──
        self._status_var = tk.StringVar(value="就绪。请输入股票代码或名称后按查询。")
        ttk.Label(self, textvariable=self._status_var, anchor=tk.W,
                  relief=tk.SUNKEN, padding=(6, 2)).pack(fill=tk.X, side=tk.BOTTOM)

    # ── 事件处理 ──────────────────────────────────────────────

    def _choose_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=self._dir_var.get())
        if d:
            self._dir_var.set(d)

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _toggle_all(self) -> None:
        checked = self._all_var.get()
        self._checked.clear()
        for iid in self._tree.get_children():
            sym = "☑" if checked else "☐"
            self._tree.set(iid, "chk", sym)
            if checked:
                self._checked.add(iid)
        self._dl_btn.config(state=tk.NORMAL if self._checked else tk.DISABLED)

    def _on_click(self, event: tk.Event) -> None:
        col = self._tree.identify_column(event.x)
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        if col == "#1":          # 勾选列
            if iid in self._checked:
                self._checked.discard(iid)
                self._tree.set(iid, "chk", "☐")
            else:
                self._checked.add(iid)
                self._tree.set(iid, "chk", "☑")
            all_ids = self._tree.get_children()
            self._all_var.set(bool(all_ids) and len(self._checked) == len(all_ids))
            self._dl_btn.config(state=tk.NORMAL if self._checked else tk.DISABLED)
        elif col == "#6":        # 操作列 — 单独下载
            idx = int(iid)
            if 0 <= idx < len(self._reports):
                self._start_downloads([self._reports[idx]], [iid])

    # ── 查询 ──────────────────────────────────────────────────

    def _do_search(self) -> None:
        query = self._query_var.get().strip()
        if not query:
            self._set_status("请输入股票代码或名称。")
            return
        self._search_btn.config(state=tk.DISABLED)
        self._clear_table()
        self._progress.start(10)
        self._set_status("正在查询，请稍候…")

        report_type = self._type_var.get()
        year_str    = self._year_var.get()
        year        = int(year_str) if year_str != "全部年份" else None
        source      = self._src_var.get()

        def worker() -> None:
            results: List[Dict] = []
            errors:  List[str]  = []

            # 新浪财经
            if source in ("新浪财经", "双源"):
                try:
                    si = sina_resolve_stock(query)
                    items = sina_fetch_reports(si["stock_id"], report_type, year)
                    results.extend(items)
                    self._stock_info = si
                except Exception as exc:
                    errors.append(f"新浪财经：{exc}")

            # 巨潮资讯
            if source in ("巨潮资讯", "双源"):
                try:
                    ci = cninfo_resolve_stock(query)
                    items = cninfo_fetch_reports(
                        ci["stock_id"], ci["org_id"],
                        ci.get("column", "szse"), ci.get("plate", ""),
                        report_type, year,
                    )
                    results.extend(items)
                    # 用公告里的 secName 补全股票名称（纯代码查询时 stock_name 为代码本身）
                    if items and (ci.get("stock_name", "") == ci.get("stock_id", "")):
                        ci["stock_name"] = items[0].get("sec_name", "") or ci["stock_name"]
                    if not self._stock_info or self._stock_info.get("stock_name") == self._stock_info.get("stock_id"):
                        self._stock_info = ci
                except Exception as exc:
                    errors.append(f"巨潮资讯：{exc}")

            # 去重（按日期+标题前 20 字）
            seen: set = set()
            deduped:  List[Dict] = []
            for item in sorted(results, key=lambda x: x["date"], reverse=True):
                key = (item["date"], item["title"][:20])
                if key not in seen:
                    seen.add(key)
                    deduped.append(item)

            self._queue.put(("search_done", deduped, errors))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_table(self) -> None:
        self._reports = []
        self._stock_info = {}
        self._checked.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._summary_var.set("")
        self._dl_btn.config(state=tk.DISABLED)
        self._all_var.set(False)

    def _populate_table(self, reports: List[Dict]) -> None:
        self._reports = reports
        self._checked.clear()
        for i, r in enumerate(reports):
            self._tree.insert(
                "", tk.END, iid=str(i),
                values=("☐", r["date"], r.get("report_year", ""), r["title"], r["source"], "下载"),
            )
        count = len(reports)
        name  = self._stock_info.get("stock_name", "")
        sid   = self._stock_info.get("stock_id", "")
        self._summary_var.set(f"{name} ({sid})  共 {count} 条")

    # ── 下载 ──────────────────────────────────────────────────

    def _download_selected(self) -> None:
        if not self._checked:
            return
        iids    = sorted(self._checked, key=lambda x: int(x))
        reports = [self._reports[int(i)] for i in iids if int(i) < len(self._reports)]
        self._start_downloads(reports, iids)

    def _start_downloads(self, reports: List[Dict], iids: List[str]) -> None:
        save_dir = self._dir_var.get().strip() or self._save_dir
        os.makedirs(save_dir, exist_ok=True)
        total = len(reports)
        self._dl_btn.config(state=tk.DISABLED)
        for iid in iids:
            self._tree.set(iid, "action", "排队中")

        def worker() -> None:
            for i, (report, iid) in enumerate(zip(reports, iids)):
                self._queue.put(("row_action", iid, "下载中", ""))
                try:
                    pdf_url = report.get("pdf_url", "")
                    # 新浪财经：pdf_url 为空，detail_url 是公告详情页，需解析出真实 PDF 链接
                    if report["source"] == "新浪财经" and not pdf_url:
                        pdf_url = sina_get_pdf_url(
                            self._stock_info.get("stock_id", ""),
                            report.get("id", ""),
                            report.get("detail_url", ""),
                        )

                    filename  = sanitize_filename(report["title"]) + ".pdf"
                    save_path = os.path.join(save_dir, filename)
                    download_pdf(pdf_url, save_path)
                    self._queue.put(("row_action", iid, "✓ 完成", "done"))
                    self._queue.put(("status", f"已下载 {i+1}/{total}：{report['title'][:40]}"))
                except Exception as exc:
                    self._queue.put(("row_action", iid, "✗ 失败", "fail"))
                    self._queue.put(("status", f"下载失败（{report['title'][:20]}）：{exc}"))

            self._queue.put(("dl_done", total, save_dir))

        threading.Thread(target=worker, daemon=True).start()

    # ── 队列轮询 ──────────────────────────────────────────────

    def _poll(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                cmd = msg[0]

                if cmd == "search_done":
                    _, reports, errors = msg
                    self._progress.stop()
                    self._search_btn.config(state=tk.NORMAL)
                    self._populate_table(reports)
                    if errors and not reports:
                        self._set_status("查询失败：" + "；".join(errors))
                    elif errors:
                        self._set_status(
                            f"查询完成，共 {len(reports)} 条。部分来源出错：{'；'.join(errors)}"
                        )
                    else:
                        self._set_status(
                            f"查询完成，共 {len(reports)} 条。"
                            "点击「下载」单独下载，或勾选后批量下载。"
                        )

                elif cmd == "row_action":
                    _, iid, text, tag = msg
                    self._tree.set(iid, "action", text)
                    if tag:
                        self._tree.item(iid, tags=(tag,))

                elif cmd == "status":
                    self._set_status(msg[1])

                elif cmd == "dl_done":
                    _, total, save_dir = msg
                    self._dl_btn.config(
                        state=tk.NORMAL if self._checked else tk.DISABLED
                    )
                    self._set_status(
                        f"下载完成，共处理 {total} 个文件。"
                        f"保存路径：{save_dir}"
                    )

        except queue.Empty:
            pass
        self.after(80, self._poll)


# ─────────────────────────── 入口 ───────────────────────────

if __name__ == "__main__":
    # PyInstaller 打包后隐藏控制台时需要这行
    if getattr(sys, "frozen", False):
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

    app = MainWindow()
    app.mainloop()
