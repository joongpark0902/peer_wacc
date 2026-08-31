"""좌측 패널: 대상기업 → 기준일 → 키워드 → 필터 → 후보 표(선택·제외·사유) → 세션 저장/열기."""
import datetime as dt
import os
import re
import threading
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog

import customtkinter as ctk

import market_data as md
import peer_search as ps
import pipeline
import session as sess_mod
import ui_theme
from settings import SESSION_DIR
from ui_theme import TEXT_SECONDARY, table_cell, table_header, zebra_bg

_TOKEN = re.compile(r"[,\s/·()]+")


def default_as_of(today=None):
    """직전 분기말."""
    t = today or dt.date.today()
    q_end = {1: (t.year - 1, 12, 31), 2: (t.year - 1, 12, 31), 3: (t.year - 1, 12, 31),
             4: (t.year, 3, 31), 5: (t.year, 3, 31), 6: (t.year, 3, 31),
             7: (t.year, 6, 30), 8: (t.year, 6, 30), 9: (t.year, 6, 30),
             10: (t.year, 9, 30), 11: (t.year, 9, 30), 12: (t.year, 9, 30)}[t.month]
    return dt.date(*q_end).isoformat()


def keywords_from_products(products):
    toks = [t for t in _TOKEN.split(products or "") if len(t) >= 2]
    return ", ".join(dict.fromkeys(toks[:6]))


class CandidatePanel:
    def __init__(self, parent, app):
        self.app = app
        self.frame = ctk.CTkFrame(parent, fg_color=ui_theme.PANEL_BG, border_width=1, border_color=ui_theme.BORDER)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(3, weight=1)
        self.rows_state = {}                 # code -> {"sel": BooleanVar, "exc": BooleanVar, "reason": StringVar}
        self._found, self._addable = [], []  # 표에서 찾기: 매치된 종목코드 / 추가 가능 KIND 행
        self._build_target(self.frame)
        self._build_filters(self.frame)
        self._build_search(self.frame)
        self._build_table(self.frame)
        self._build_bottom(self.frame)

    # ── 대상 ────────────────────────────────────────────────────────────
    def _build_target(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text="대상기업", font=ctk.CTkFont(size=15, weight="bold"), text_color=ui_theme.ACCENT).grid(row=0, column=0, sticky="w")
        self.listed_seg = ctk.CTkSegmentedButton(f, values=["상장", "비상장"], command=self._on_listed_toggle, width=140)
        self.listed_seg.set("상장")
        self.listed_seg.grid(row=0, column=2, sticky="e")

        self.name_var = tk.StringVar()
        ctk.CTkLabel(f, text="회사명").grid(row=1, column=0, sticky="w", pady=2)
        e = ctk.CTkEntry(f, textvariable=self.name_var)
        e.grid(row=1, column=1, sticky="ew", padx=6)
        e.bind("<Return>", lambda _e: self._find_target() if self.listed_seg.get() == "상장" else None)
        self.find_btn = ctk.CTkButton(f, text="찾기", width=70, command=self._find_target)
        self.find_btn.grid(row=1, column=2)

        self.match_box = tk.Listbox(f, height=4, **ui_theme.LISTBOX_STYLE)
        self.match_box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 2))
        self.match_box.bind("<<ListboxSelect>>", self._on_pick_target)
        self._matches = []

        ctk.CTkLabel(f, text="업종").grid(row=3, column=0, sticky="w", pady=2)
        self.industry_var = tk.StringVar()
        self._industries = []
        ie = ctk.CTkEntry(f, textvariable=self.industry_var, placeholder_text="업종명 일부 입력 → 아래 목록에서 선택 (예: 소 → 소프트웨어 개발 및 공급업)")
        ie.grid(row=3, column=1, columnspan=2, sticky="ew", padx=6)
        ie.bind("<KeyRelease>", self._on_industry_typed)
        self.industry_box = tk.Listbox(f, height=5, **ui_theme.LISTBOX_STYLE)
        self.industry_box.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(2, 2))
        self.industry_box.bind("<<ListboxSelect>>", self._on_pick_industry)
        self.industry_box.grid_remove()          # 입력 전엔 숨김

        self.target_info = ctk.CTkLabel(f, text="", text_color=TEXT_SECONDARY, anchor="w", justify="left")
        self.target_info.grid(row=4, column=0, columnspan=3, sticky="ew")

    def _on_industry_typed(self, _e=None):
        q = self.industry_var.get().strip().lower()
        hits = [x for x in self._industries if q and q in x.lower()]
        hits.sort(key=lambda x: (not x.lower().startswith(q), x))      # '소' → 소프트웨어… 가 소매업보다 먼저
        if q in {x.lower() for x in self._industries}:
            hits = []                              # 정확히 고른 상태면 목록 숨김
        self.industry_box.delete(0, "end")
        for x in hits[:30]:
            self.industry_box.insert("end", x)
        if hits:
            self.industry_box.configure(height=min(6, len(hits[:30])))
            self.industry_box.grid()
        else:
            self.industry_box.grid_remove()

    def _on_pick_industry(self, _e):
        sel = self.industry_box.curselection()
        if not sel:
            return
        self.industry_var.set(self.industry_box.get(sel[0]))
        self.industry_box.grid_remove()
        self.app.sess["target"]["industry"] = self.industry_var.get()

    def _on_listed_toggle(self, value):
        listed = value == "상장"
        self.find_btn.configure(state="normal" if listed else "disabled")
        self.match_box.delete(0, "end")
        self.app.sess["target"]["listed"] = listed
        if not listed:
            self.app.sess["target"]["code"] = ""
            self.target_info.configure(text="비상장: 회사명 입력 → 업종 선택(같은 업종 전부 후보) + 키워드로 좁히기")

    def _find_target(self):
        kw = self.name_var.get().strip().lower()
        rows = self.app.kind_rows or []
        self._matches = [r for r in rows if kw and kw in r["name"].lower()][:30]
        self.match_box.delete(0, "end")
        for r in self._matches:
            self.match_box.insert("end", f"{r['name']} ({r['code']}) · {r['industry']}")
        if not self._matches:
            self.target_info.configure(text="일치하는 상장사가 없습니다 (비상장이면 상단에서 '비상장' 선택)")

    def _on_pick_target(self, _e):
        sel = self.match_box.curselection()
        if not sel:
            return
        r = self._matches[sel[0]]
        t = self.app.sess["target"]
        t.update({"name": r["name"], "listed": True, "code": r["code"], "industry": r["industry"], "ksic": ""})
        self.name_var.set(r["name"])
        self.industry_var.set(r["industry"])
        if not self.kw_var.get().strip():
            self.kw_var.set(keywords_from_products(r["products"]))
        self.target_info.configure(text=f"주요제품: {r['products']} · 상장 {r['listed']} · KSIC 조회 중…")
        threading.Thread(target=self._fetch_target_ksic, args=(r["code"],), daemon=True).start()

    def _fetch_target_ksic(self, code):
        try:
            cc = self.app.fetchers["corp_map"]().get(code)
            comp = self.app.fetchers["company"](cc) if cc else {}
            ksic = comp.get("induty_code") or ""
        except Exception as e:
            ksic = ""
            self.app.log(f"대상 KSIC 조회 실패: {e}")
        self.app.ui(self._set_target_ksic, ksic)

    def _set_target_ksic(self, ksic):
        self.app.sess["target"]["ksic"] = ksic
        cur = self.target_info.cget("text").split(" · KSIC")[0]
        self.target_info.configure(text=f"{cur} · KSIC {ksic or '없음'}")

    # ── 기준일·키워드·필터 ───────────────────────────────────────────────
    def _build_filters(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text="기준일").grid(row=0, column=0, sticky="w")
        self.as_of_var = tk.StringVar(value=default_as_of())
        af = ctk.CTkFrame(f, fg_color="transparent")
        af.grid(row=0, column=1, columnspan=2, sticky="w")
        ctk.CTkEntry(af, textvariable=self.as_of_var, width=110).grid(row=0, column=0, padx=6)
        ctk.CTkLabel(af, text="재무 기준일").grid(row=0, column=1, padx=(12, 4))
        # 주가·금리는 기준일, 재무제표만 지정 분기말 이하 최신 보고서로 — 반기 미공시 기간 등에 피어 재무 시점을 통일
        self.fs_seg = ctk.CTkSegmentedButton(af, values=["자동", "3월말", "6월말", "9월말", "12월말"], width=280)
        self.fs_seg.set("자동")
        self.fs_seg.grid(row=0, column=2)
        ctk.CTkLabel(f, text="키워드(쉼표 구분)").grid(row=1, column=0, sticky="w", pady=2)
        self.kw_var = tk.StringVar()
        e = ctk.CTkEntry(f, textvariable=self.kw_var)
        e.grid(row=1, column=1, columnspan=2, sticky="ew", padx=6)
        e.bind("<Return>", lambda _e: self.search())
        ctk.CTkLabel(f, text="제외 키워드").grid(row=2, column=0, sticky="w", pady=2)
        self.neg_var = tk.StringVar(value=ps.DEFAULT_EXCLUDE_KEYWORDS)
        ctk.CTkEntry(f, textvariable=self.neg_var, placeholder_text="사명·주요제품에 있으면 감점 (-5/개)").grid(row=2, column=1, columnspan=2, sticky="ew", padx=6)
        k = ctk.CTkFrame(f, fg_color="transparent")
        k.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 0))
        ctk.CTkLabel(k, text="KSIC 코드군(선택)").grid(row=0, column=0, sticky="w")
        self.ksic_var = tk.StringVar()
        ctk.CTkEntry(k, textvariable=self.ksic_var, width=300, placeholder_text="예: C29299, C29177, C25100 — 앞4자리 +2, 앞3자리 +1").grid(row=0, column=1, padx=6)
        ctk.CTkLabel(k, text="대상 시총(억, 선택)").grid(row=0, column=2, padx=(12, 0))
        self.target_cap_var = tk.StringVar()
        ctk.CTkEntry(k, textvariable=self.target_cap_var, width=90, placeholder_text="0.2x~5x +2").grid(row=0, column=3, padx=6)

        g = ctk.CTkFrame(f, fg_color="transparent")
        g.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.mk_kospi = tk.BooleanVar(value=True)
        self.mk_kosdaq = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(g, text="유가", variable=self.mk_kospi, width=60).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkCheckBox(g, text="코스닥", variable=self.mk_kosdaq, width=70).grid(row=0, column=1, padx=6)
        ctk.CTkLabel(g, text="시총(억)").grid(row=0, column=2, padx=(12, 2))
        self.cap_min = tk.StringVar(); self.cap_max = tk.StringVar()
        ctk.CTkEntry(g, textvariable=self.cap_min, width=70, placeholder_text="하한").grid(row=0, column=3)
        ctk.CTkLabel(g, text="~").grid(row=0, column=4, padx=2)
        ctk.CTkEntry(g, textvariable=self.cap_max, width=70, placeholder_text="상한").grid(row=0, column=5)
        self.listed_min = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(g, text="상장 2년 이상만", variable=self.listed_min).grid(row=0, column=6, padx=(12, 0))
        self.search_btn = ctk.CTkButton(g, text="후보 검색", width=100, command=self.search)
        self.search_btn.grid(row=0, column=7, padx=(12, 0))

    # ── 표에서 찾기 (회사가 준 피어 리스트 붙여넣기 → 하이라이트·후보에 추가·일괄 선택) ─────
    def _build_search(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 0))
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text="표에서 찾기").grid(row=0, column=0, sticky="w")
        self.find_var = tk.StringVar()
        e = ctk.CTkEntry(f, textvariable=self.find_var,
                         placeholder_text="회사명·코드 (쉼표·탭 구분 — 회사가 준 피어 리스트 붙여넣기)")
        e.grid(row=0, column=1, sticky="ew", padx=6)
        e.bind("<KeyRelease>", lambda _e: self._on_find_typed())
        self.select_found_btn = ctk.CTkButton(f, text="찾은 회사 선택 ☑", width=130, command=self.select_found, state="disabled")
        self.select_found_btn.grid(row=0, column=2, padx=(0, 6))
        self.add_found_btn = ctk.CTkButton(f, text="후보에 추가", width=90, command=self.add_found, state="disabled")
        self.add_found_btn.grid(row=0, column=3)
        self.find_label = ctk.CTkLabel(f, text="", text_color=TEXT_SECONDARY, anchor="w", justify="left")
        self.find_label.grid(row=1, column=0, columnspan=4, sticky="ew")
        self.count_label = ctk.CTkLabel(f, text="후보 0개", text_color=TEXT_SECONDARY, anchor="w")
        self.count_label.grid(row=2, column=0, columnspan=4, sticky="ew")

    def _on_find_typed(self):
        text = self.find_var.get()
        # 전체 후보를 대상으로 찾는다 — 표 상한(MAX_ROWS) 밖 후보를 '후보에 없음'으로 오분류하지 않게
        self._found, self._addable, missing = ps.find_names(
            text, self.app.candidates, self.app.kind_rows or [])
        for code in self.rows_state:
            tags = [t for t in self.tree.item(code, "tags") if t != "found"]
            if code in self._found:
                tags = ["found"] + tags              # 첫 태그가 배경색 우선
            self.tree.item(code, tags=tags)
        visible = [c for c in self._found if c in self.rows_state]
        if visible:
            self.tree.see(visible[0])
        self.select_found_btn.configure(state="normal" if visible else "disabled")
        self.add_found_btn.configure(state="normal" if self._addable else "disabled")
        parts = []
        if text.strip():
            parts.append(f"찾음 {len(self._found)}개")
            beyond = len(self._found) - len(visible)
            if beyond:
                parts.append(f"표 밖 {beyond}개(후보 {self.MAX_ROWS}행 초과 — 검색·집계엔 포함)")
            if self._addable:
                parts.append("후보에 없음(상장목록엔 있음): " + ", ".join(dict.fromkeys(r["name"] for r in self._addable)))
            if missing:
                parts.append("상장목록에도 없음: " + ", ".join(missing))
        self.find_label.configure(text=" · ".join(parts))

    def select_found(self):
        for code in self._found:
            st = self.rows_state.get(code)
            if st and not st["exc"].get() and not st["sel"].get():
                st["sel"].set(True)
                self._on_select(code)

    def add_found(self):
        as_of = self.as_of_var.get().strip()
        manual = self.app.sess.setdefault("manual_codes", [])
        seen = {r["code"] for r in self.app.candidates}
        added = []
        for row in self._addable:
            if row["code"] in seen:
                continue
            seen.add(row["code"])
            self.app.candidates.append(ps.manual_row(row, as_of, caps=self.app.caps))
            if row["code"] not in manual:
                manual.append(row["code"])
            added.append(row["name"])
        if added:
            self.render()                            # render 끝에서 찾기 하이라이트 재적용
            self.app.set_status("후보에 추가: " + ", ".join(added))

    # ── 후보 표 (ttk.Treeview — 행당 위젯을 만들지 않아 수천 행도 즉시) ────────────────────────
    _COLS = [("sel", "선택", 40, "center"), ("rec", "추천", 44, "center"), ("name", "회사명", 120, "w"), ("market", "시장", 44, "center"),
             ("code", "코드", 60, "center"), ("industry", "업종", 150, "w"), ("products", "주요제품", 200, "w"),
             ("hits", "적중", 70, "w"), ("listed", "상장일", 78, "center"), ("settle", "결산", 40, "center"),
             ("cap", "시총(억)", 70, "e"), ("flags", "추천 이유 · 플래그", 260, "w"), ("exc", "제외", 40, "center"),
             ("reason", "제외 사유", 120, "w")]
    MAX_ROWS = 3000

    def _build_table(self, parent):
        box = ctk.CTkFrame(parent, fg_color=ui_theme.SURFACE, corner_radius=0)
        box.grid(row=3, column=0, sticky="nsew", padx=6, pady=4)
        box.grid_columnconfigure(0, weight=1); box.grid_rowconfigure(0, weight=1)
        st = ttk.Style()
        st.configure("Cand.Treeview", font=(ui_theme.FONT_FAMILY, 10), rowheight=26, borderwidth=0,
                     background=ui_theme.SURFACE, fieldbackground=ui_theme.SURFACE)
        st.configure("Cand.Treeview.Heading", font=(ui_theme.FONT_FAMILY, 10, "bold"), background=ui_theme.HEADER_FILL,
                     foreground=ui_theme.HEADER_TEXT, relief="flat", padding=(4, 6))
        st.map("Cand.Treeview.Heading", background=[("active", ui_theme.HEADER_FILL)])
        st.map("Cand.Treeview", background=[("selected", ui_theme.SURFACE)], foreground=[("selected", ui_theme.TEXT_PRIMARY)])
        self.tree = ttk.Treeview(box, columns=[c[0] for c in self._COLS], show="headings", style="Cand.Treeview", selectmode="none")
        for key, title, width, anchor in self._COLS:
            self.tree.heading(key, text=title, anchor="center")
            self.tree.column(key, width=width, minwidth=30, anchor=anchor, stretch=(key in ("industry", "products")))
        self.tree.tag_configure("odd", background=ui_theme.ROW_STRIPE)
        self.tree.tag_configure("excluded", foreground=TEXT_SECONDARY)
        self.tree.tag_configure("rec", background="#FFF3C4")          # 추천 행 연노랑
        self.tree.tag_configure("found", background="#C6D9F1")        # 찾은 행 하늘색(테마 헤더색)
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); vs.grid(row=0, column=1, sticky="ns"); hs.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", self._on_tree_double)
        self._reason_popup = None

    def _num(self, var):
        s = var.get().strip().replace(",", "")
        return float(s) if s else None

    def ensure_caps(self, as_of, then):
        """시총 필터가 켜졌는데 전종목 시총이 없으면 백그라운드로 받아온 뒤 then() 을 부른다."""
        if self.app.caps or not self.app.krx_ok:
            then(); return
        self.app.set_status("기준일 전종목 시총을 KRX에서 받는 중… (시총 필터용, 한 번만)")

        def run():
            try:
                self.app.caps = md.market_caps_all(as_of)
            except Exception as e:
                self.app.log(f"시총 조회 실패: {e}")
            self.app.ui(then)
        threading.Thread(target=run, daemon=True).start()

    def search(self):
        kws = ps.parse_keywords(self.kw_var.get())
        industry = self.industry_var.get().strip()
        if not kws and not industry and not self.ksic_var.get().strip():
            self.app.set_status("키워드·업종·KSIC 코드군 중 하나는 있어야 합니다 (없으면 전 상장사가 잡혀 검색하지 않습니다).")
            return
        as_of = self.as_of_var.get().strip()
        try:
            dt.date.fromisoformat(as_of)
        except ValueError:
            self.app.set_status("기준일은 YYYY-MM-DD 형식으로 입력하세요.")
            return
        if not self.app.kind_rows:
            self.app.set_status("상장사 목록을 아직 못 받았습니다. 잠시 후 다시 시도하세요.")
            return
        want_cap = bool(self._num(self.cap_min) or self._num(self.cap_max))
        if want_cap and not self.app.caps:
            if self.app.krx_ok:
                self.ensure_caps(as_of, self.search)          # 받아온 뒤 다시 search()
                return
            self.app.set_status("시총 필터는 KRX 로그인이 필요합니다. 필터 없이 검색합니다.")
        markets = [m for m, v in (("유가", self.mk_kospi.get()), ("코스닥", self.mk_kosdaq.get())) if v]
        caps = self.app.caps if (want_cap and self.app.caps) else None
        target_ksic = self.app.sess["target"].get("ksic") if self.app.sess["target"].get("listed") else None
        negs = ps.parse_keywords(self.neg_var.get())
        ksic_codes = [c.strip().upper().lstrip("C") for c in self.ksic_var.get().split(",") if c.strip()]
        tcap = self._num(self.target_cap_var)
        found = ps.search(self.app.kind_rows, kws, as_of, markets=markets,
                          cap_min=self._num(self.cap_min) if caps else None,
                          cap_max=self._num(self.cap_max) if caps else None,
                          caps=self.app.caps or caps, target_ksic=target_ksic,
                          listed_min_days=730 if self.listed_min.get() else None,
                          industry=industry, exclude_keywords=negs, ksic_codes=ksic_codes,
                          target_cap=tcap * 1e8 if tcap else None)
        self.app.candidates = ps.rank(found)                 # 추천 5개가 맨 위
        by_code = {r["code"]: r for r in self.app.kind_rows}
        seen = {r["code"] for r in self.app.candidates}
        for code in self.app.sess.get("manual_codes", []):   # 수동추가 행은 재검색에도 유지
            r = by_code.get(code)
            if r and code not in seen:
                self.app.candidates.append(ps.manual_row(r, as_of, caps=self.app.caps))
        self.app.sess["target"]["industry"] = industry
        self.app.sess.update({"as_of": as_of, "keywords": kws,
                              "filters": {"markets": markets, "cap_min": self._num(self.cap_min),
                                          "cap_max": self._num(self.cap_max), "listed_min": self.listed_min.get(),
                                          "exclude_keywords": negs, "ksic_codes": ksic_codes, "target_cap": tcap}})
        self.render()

    @staticmethod
    def _mark(b):
        return "☑" if b else "☐"

    def _row_values(self, r, st):
        hits = (["업종"] if r.get("same_industry") else []) + r["hits"]
        return (self._mark(st["sel"].get()), "★" if r.get("recommended") else "", r["name"], r["market"], r["code"], r["industry"], r["products"],
                ", ".join(hits), r["listed"], r["settle_month"],
                "" if r["cap_eok"] is None else f"{r['cap_eok']:,.0f}",
                (("★ " if r.get("recommended") else "") + r.get("reason", "")) if "reason" in r else ", ".join(r["flags"]),
                self._mark(st["exc"].get()), st["reason"].get())

    def render(self):
        self.tree.delete(*self.tree.get_children())
        self.rows_state = {}
        saved = self.app.sess.get("candidates", {})
        shown = self.app.candidates[:self.MAX_ROWS]
        for i, r in enumerate(shown):
            st0 = saved.get(r["code"], {})
            st = {"sel": tk.BooleanVar(value=bool(st0.get("selected"))), "exc": tk.BooleanVar(value=bool(st0.get("excluded"))),
                  "reason": tk.StringVar(value=st0.get("reason", "")), "row": r}
            tags = (["rec"] if r.get("recommended") else ["odd" if i % 2 else "even"]) + (["excluded"] if st["exc"].get() else [])
            st["iid"] = self.tree.insert("", "end", iid=r["code"], values=self._row_values(r, st), tags=tags)
            self.rows_state[r["code"]] = st
        if self.find_var.get().strip():
            self._on_find_typed()                # 표를 다시 그린 뒤 찾기 하이라이트 재적용
        self._update_count()

    def _update_count(self):
        n = len(self.app.candidates)
        extra = f" · 앞 {self.MAX_ROWS}개만 표시" if n > self.MAX_ROWS else ""
        rec = sum(1 for r in self.app.candidates if r.get("recommended"))
        self.count_label.configure(text=f"후보 {n}개 · ★추천 {rec}개(업종+3 · KSIC+2/+1 · 키워드+2/개 · 시총유사+2 · 제외어−5 · 신규상장−5) · 선택 {len(self.selected_codes())}개{extra}")

    def _refresh_row(self, code):
        st = self.rows_state[code]
        r = st["row"]
        tags = ((["found"] if code in self._found else [])
                + (["rec"] if r.get("recommended") else ["odd" if self.tree.index(code) % 2 else "even"])
                + (["excluded"] if st["exc"].get() else []))
        self.tree.item(code, values=self._row_values(r, st), tags=tags)

    def _on_tree_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        code = self.tree.identify_row(event.y)
        if not code or code not in self.rows_state:
            return
        key = self._COLS[int(col[1:]) - 1][0]
        st = self.rows_state[code]
        if key == "sel":
            st["sel"].set(not st["sel"].get()); self._on_select(code)
        elif key == "exc":
            st["exc"].set(not st["exc"].get()); self._on_exclude(code)

    def _on_tree_double(self, event):
        col = self.tree.identify_column(event.x); code = self.tree.identify_row(event.y)
        if not code or code not in self.rows_state or self._COLS[int(col[1:]) - 1][0] != "reason":
            return
        x, y, w, h = self.tree.bbox(code, col)
        st = self.rows_state[code]
        if self._reason_popup is not None:
            self._reason_popup.destroy()
        cb = ttk.Combobox(self.tree, textvariable=st["reason"], values=ps.EXCLUDE_REASONS, width=max(12, w // 8))
        cb.place(x=x, y=y, width=w, height=h)
        cb.focus_set()
        self._reason_popup = cb

        def done(_e=None):
            self._on_reason(code)
            if self._reason_popup is cb:
                cb.destroy(); self._reason_popup = None
        cb.bind("<<ComboboxSelected>>", done); cb.bind("<Return>", done); cb.bind("<FocusOut>", done)

    def _state(self, code):
        return self.app.sess["candidates"].setdefault(code, {"selected": False, "excluded": False, "reason": ""})

    def _on_select(self, code):
        s, v = self._state(code), self.rows_state[code]
        if v["sel"].get() and v["exc"].get():
            v["exc"].set(False); s["excluded"] = False
        s["selected"] = v["sel"].get()
        if self.tree.exists(code): self._refresh_row(code)
        self._update_count()

    def _on_exclude(self, code):
        s, v = self._state(code), self.rows_state[code]
        s["excluded"] = v["exc"].get()
        if s["excluded"]:
            v["sel"].set(False); s["selected"] = False
        if self.tree.exists(code): self._refresh_row(code)
        self._update_count()

    def _on_reason(self, code):
        self._state(code)["reason"] = self.rows_state[code]["reason"].get()
        if self.tree.exists(code): self._refresh_row(code)

    def selected_codes(self):
        return [c for c, v in self.rows_state.items() if v["sel"].get() and not v["exc"].get()]

    def kind_row(self, code):
        return self.rows_state[code]["row"]

    def candidates_for_report(self):
        out = []
        for r in self.app.candidates:
            v = self.rows_state.get(r["code"])
            out.append(dict(r, excluded=bool(v and v["exc"].get()), reason=(v["reason"].get() if v else "")))
        return out

    # ── 세션 ────────────────────────────────────────────────────────────
    def _build_bottom(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkButton(f, text="세션 저장", width=90, command=self.save_session).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkButton(f, text="세션 열기", width=90, command=self.open_session).grid(row=0, column=1)
        f.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(f, text="선택한 피어로 요약 탭 →", width=170, command=self._go_summary).grid(row=0, column=3, sticky="e")

    def _go_summary(self):
        if not self.selected_codes():
            self.app.set_status("피어를 먼저 선택하세요 (선택 열 클릭).")
            return
        self.app.show_summary()
        self.app.summary_panel.load_peers()

    def collect_session(self):
        s = self.app.sess
        s["target"]["name"] = self.name_var.get().strip() or s["target"]["name"]
        s["target"]["listed"] = self.listed_seg.get() == "상장"
        s["target"]["industry"] = self.industry_var.get()
        try:
            s["target"]["cap_eok"] = self._num(self.target_cap_var)  # SRP 분위 판정에도 쓴다(억)
        except ValueError:
            s["target"]["cap_eok"] = None
        s["as_of"] = self.as_of_var.get().strip()
        s["fs_month"] = {"3월말": 3, "6월말": 6, "9월말": 9, "12월말": 12}.get(self.fs_seg.get())
        try:
            s["fs_as_of"] = pipeline.fs_quarter_end(s["as_of"], s["fs_month"])
        except ValueError:
            s["fs_as_of"] = None
        s["keywords"] = ps.parse_keywords(self.kw_var.get())
        return s

    def save_session(self):
        s = self.collect_session()
        if not s["target"]["name"]:
            self.app.set_status("대상기업 이름을 먼저 입력하세요.")
            return
        p = sess_mod.save(s)
        self.app.set_status(f"세션 저장: {p}")

    def open_session(self):
        os.makedirs(SESSION_DIR, exist_ok=True)
        p = filedialog.askopenfilename(initialdir=SESSION_DIR, filetypes=[("세션", "*.json")])
        if not p:
            return
        self.apply_session(sess_mod.load(p))
        self.app.set_status(f"세션 열기: {p}")

    def apply_session(self, s):
        self.app.sess = s
        t = s["target"]
        self.listed_seg.set("상장" if t.get("listed") else "비상장")
        self.name_var.set(t.get("name", ""))
        self.industry_var.set(t.get("industry", ""))
        self.as_of_var.set(s.get("as_of", default_as_of()))
        self.fs_seg.set({3: "3월말", 6: "6월말", 9: "9월말", 12: "12월말"}.get(s.get("fs_month"), "자동"))
        self.kw_var.set(", ".join(s.get("keywords", [])))
        fl = s.get("filters", {})
        self.mk_kospi.set("유가" in fl.get("markets", ["유가"]))
        self.mk_kosdaq.set("코스닥" in fl.get("markets", ["코스닥"]))
        self.cap_min.set("" if fl.get("cap_min") is None else str(fl["cap_min"]))
        self.cap_max.set("" if fl.get("cap_max") is None else str(fl["cap_max"]))
        self.listed_min.set(bool(fl.get("listed_min")))
        self.neg_var.set(", ".join(fl.get("exclude_keywords", ps.parse_keywords(ps.DEFAULT_EXCLUDE_KEYWORDS))))
        self.ksic_var.set(", ".join(fl.get("ksic_codes", [])))
        self.target_cap_var.set("" if fl.get("target_cap") is None else str(fl["target_cap"]))
        self.app.summary_panel.apply_session(s)
        if self.app.kind_rows:
            self.search()

    def set_industries(self, rows):
        self._industries = sorted({r["industry"] for r in rows if r.get("industry")})
