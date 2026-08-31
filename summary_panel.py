"""우측 패널: 베타 소스 토글 · 한공회 파일 · 피어 자료 불러오기 · 요약 표 · 집계 · 보고서 만들기."""
import datetime as dt
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk
import tkinter.ttk as ttk

import beta as B
import kicpa_beta
import kofia
import market_data as md
import pipeline
import report
import settings
import ui_theme
from settings import DOWNLOADS_DIR
from ui_theme import NEGATIVE, TEXT_SECONDARY, table_cell, table_header, zebra_bg

_HEAD = ["회사명", "코드", "종가", "E(억)", "D(억)", "D/E", "세율", "β raw", "β Blume", "n", "R²",
         "한공회 실질", "한공회 조정", "포인트", "차이", "βL 적용", "βU", "집계", "상태/플래그", "부채"]
_W = [110, 56, 64, 70, 64, 60, 46, 60, 60, 36, 46, 66, 66, 46, 56, 60, 60, 40, 200, 50]


def _f(v, fmt="{:.4f}"):
    return "" if v is None else fmt.format(v)


class SummaryPanel:
    def __init__(self, parent, app):
        self.app = app
        self.rows = []
        self.include_vars = {}
        self.frame = ctk.CTkFrame(parent, fg_color=ui_theme.PANEL_BG, border_width=1, border_color=ui_theme.BORDER)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(2, weight=1)
        self._build_top(self.frame)
        self._build_table(self.frame)
        self._build_bottom(self.frame)
        self.render()

    def _build_top(self, parent):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(f, text="요약", font=ctk.CTkFont(size=15, weight="bold"), text_color=ui_theme.ACCENT).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(f, text="베타 소스").grid(row=0, column=1, padx=(16, 4))
        self.src_seg = ctk.CTkSegmentedButton(f, values=["산출(KRX)", "한공회 파일"], command=self._on_source, width=180)
        self.src_seg.set("한공회 파일")
        self.src_seg.grid(row=0, column=2)
        ctk.CTkButton(f, text="한공회 파일 열기", width=120, command=self.open_kicpa).grid(row=0, column=3, padx=(8, 0))
        ctk.CTkLabel(f, text="목표 D/E").grid(row=0, column=4, padx=(16, 4))
        self.de_seg = ctk.CTkSegmentedButton(f, values=["평균", "중앙값"], command=self._on_de, width=120)
        self.de_seg.set("평균")
        self.de_seg.grid(row=0, column=5)
        ctk.CTkLabel(f, text="대상 세율").grid(row=0, column=6, padx=(16, 4))
        self.tax_var = tk.StringVar(value="27.5")
        e = ctk.CTkEntry(f, textvariable=self.tax_var, width=56)
        e.grid(row=0, column=7)
        e.bind("<FocusOut>", lambda _e: self._on_tax())
        ctk.CTkLabel(f, text="%").grid(row=0, column=8)
        self.lease_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(f, text="리스부채 포함(D)", variable=self.lease_var, command=self._on_lease).grid(row=0, column=9, padx=(16, 0))
        ctk.CTkLabel(f, text="대상 순자산(억)").grid(row=0, column=10, padx=(16, 4))
        self.net_assets_var = tk.StringVar()
        na = ctk.CTkEntry(f, textvariable=self.net_assets_var, width=70, placeholder_text="SRP용")
        na.grid(row=0, column=11)
        na.bind("<FocusOut>", lambda _e: self._on_net_assets())

        g = ctk.CTkFrame(parent, fg_color="transparent")
        g.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 2))
        g.grid_columnconfigure(2, weight=1)
        self.load_btn = ctk.CTkButton(g, text="피어 자료 불러오기", width=140, command=self.load_peers)
        self.load_btn.grid(row=0, column=0)
        self.report_btn = ctk.CTkButton(g, text="보고서 만들기", width=120, command=self.make_report, state="disabled")
        self.report_btn.grid(row=0, column=1, padx=(8, 0))
        self.progress = ctk.CTkLabel(g, text="", text_color=TEXT_SECONDARY, anchor="w")
        self.progress.grid(row=0, column=2, sticky="ew", padx=12)
        self.kicpa_label = ctk.CTkLabel(g, text="한공회 파일: 없음", text_color=TEXT_SECONDARY, anchor="e")
        self.kicpa_label.grid(row=0, column=3, sticky="e")

    def _build_bottom(self, parent):
        f = ctk.CTkFrame(parent, fg_color=ui_theme.SURFACE, border_width=1, border_color=ui_theme.BORDER)
        f.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.agg_label = ctk.CTkLabel(f, text="집계 없음", anchor="w", justify="left", font=ctk.CTkFont(size=13, weight="bold"), text_color=ui_theme.ACCENT)
        self.agg_label.grid(row=0, column=0, sticky="w", padx=10, pady=8)
        self.result_label = ctk.CTkLabel(f, text="", anchor="w", text_color=TEXT_SECONDARY)
        self.result_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))

    # ── 옵션 ────────────────────────────────────────────────────────────
    def _on_source(self, v):
        self.app.sess["beta_source"] = "kicpa" if v == "한공회 파일" else "calc"
        self.render()

    def _on_de(self, v):
        self.app.sess["de_method"] = "median" if v == "중앙값" else "mean"
        self.render()

    def _on_tax(self):
        try:
            self.app.sess["tax_target"] = float(self.tax_var.get().replace("%", "")) / 100
        except ValueError:
            self.tax_var.set(f"{self.app.sess['tax_target'] * 100:g}")
        self.render()

    def _on_lease(self):
        self.app.sess["include_lease"] = bool(self.lease_var.get())
        self.render()

    def _on_net_assets(self):
        """비상장 대상 SRP 분위 판정용(억). 상장 대상은 후보군 탭 '대상 시총'이 우선한다."""
        txt = self.net_assets_var.get().replace(",", "").strip()
        try:
            self.app.sess["target"]["net_assets_eok"] = float(txt) if txt else None
        except ValueError:
            v = self.app.sess["target"].get("net_assets_eok")
            self.net_assets_var.set("" if v is None else f"{v:g}")

    def force_kicpa_source(self):
        self.src_seg.set("한공회 파일")
        self.app.sess["beta_source"] = "kicpa"
        self.src_seg.configure(state="disabled")
        self.progress.configure(text="KRX 미로그인 — 베타 소스는 한공회 파일만 가능", text_color=NEGATIVE)

    def apply_session(self, s):
        self.src_seg.set("한공회 파일" if s.get("beta_source") == "kicpa" else "산출(KRX)")
        self.de_seg.set("중앙값" if s.get("de_method") == "median" else "평균")
        self.tax_var.set(f"{s.get('tax_target', 0.275) * 100:g}")
        self.lease_var.set(bool(s.get("include_lease", True)))
        na = s.get("target", {}).get("net_assets_eok")
        self.net_assets_var.set("" if na is None else f"{na:g}")
        if s.get("kicpa_path") and os.path.exists(s["kicpa_path"]):
            self._load_kicpa(s["kicpa_path"])
        self.render()

    # ── 한공회 ──────────────────────────────────────────────────────────
    def open_kicpa(self):
        p = filedialog.askopenfilename(filetypes=[("한공회 베타", "*.xlsx *.xls *.csv"), ("모든 파일", "*.*")])
        if p:
            self._load_kicpa(p)

    def _load_kicpa(self, p):
        try:
            self.app.kicpa = kicpa_beta.load(p)
        except kicpa_beta.FormatError as e:
            self.progress.configure(text=f"한공회 파일 형식 오류 — 열: {e.columns}", text_color=NEGATIVE)
            return
        except Exception as e:
            self.progress.configure(text=f"한공회 파일 열기 실패: {e}", text_color=NEGATIVE)
            return
        self.app.sess["kicpa_path"] = p
        if self.app.cfg.get("kicpa_path") != p:                      # 다음 실행 시 자동 로드용
            self.app.cfg["kicpa_path"] = p
            try:
                settings.save_config(self.app.cfg)
            except OSError as e:
                self.app.log(f"config 저장 실패: {e}")
        dates = {v.get("base_date") for v in self.app.kicpa.values()} - {None}
        self.kicpa_label.configure(text=f"한공회 파일: {os.path.basename(p)} ({len(self.app.kicpa)}종목, 기준일 {', '.join(sorted(dates)) or '?'})")
        self.recheck_kicpa_date()
        for p_ in self.app.peers_loaded:
            k = self.app.kicpa.get(p_["code"])
            p_["kicpa"] = {kk: k.get(kk) for kk in ("base_date", "close", "raw", "adjusted", "points")} if k else None
            p_["close_kicpa"] = k.get("close") if k else None
        self.render()

    def recheck_kicpa_date(self, as_of=None):
        """한공회 파일 기준일 ≠ 앱 기준일 경고를 갱신 — 기준일을 맞추면 지운다(경고가 계속 떠있지 않게)."""
        if not self.app.kicpa:
            return
        dates = {v.get("base_date") for v in self.app.kicpa.values()} - {None}
        as_of = as_of or self.app.sess.get("as_of")
        if dates and as_of not in dates:
            self.progress.configure(text=f"주의: 한공회 기준일 {sorted(dates)} ≠ 앱 기준일 {as_of}", text_color=NEGATIVE)
            self._kicpa_warned = True
        elif getattr(self, "_kicpa_warned", False):
            self.progress.configure(text="")
            self._kicpa_warned = False

    def reset(self):
        """옵션·표·메시지를 초기값으로 (app.reset 에서 호출 — sess 는 이미 새것, 한공회 파일은 유지)."""
        self.apply_session(self.app.sess)
        self.progress.configure(text="", text_color=TEXT_SECONDARY)
        self._kicpa_warned = False
        self.result_label.configure(text="")
        self.report_btn.configure(state="disabled")
        self.rows, self.include_vars = [], {}
        self.render()

    # ── 피어 로드 ───────────────────────────────────────────────────────
    def load_peers(self):
        codes = self.app.candidate_panel.selected_codes()
        if not codes:
            self.progress.configure(text="후보군 탭에서 피어를 선택하세요 (선택 열 클릭).", text_color=NEGATIVE)
            return
        if not self.app.api_key:
            self.progress.configure(text="DART 인증키가 없습니다 (설정).", text_color=NEGATIVE)
            return
        self.app.candidate_panel.collect_session()
        self.load_btn.configure(state="disabled")
        self.report_btn.configure(state="disabled")
        threading.Thread(target=self._load_worker, args=(codes,), daemon=True).start()

    def _load_worker(self, codes):
        as_of = self.app.sess["as_of"]
        fs_as_of = self.app.sess.get("fs_as_of")
        tax = self.app.sess["tax_target"]
        done = {"n": 0}

        def one(code):
            row = self.app.candidate_panel.kind_row(code)
            ov = self.app.sess["peer_overrides"].get(code, {})
            p = pipeline.load_peer(code, row, as_of, self.app.fetchers, tax=tax, tax_override=ov.get("tax"),
                                   kicpa=self.app.kicpa.get(code), log=self.app.log,
                                   debt_override=ov.get("debt_include"), fs_as_of=fs_as_of)
            if ov.get("include") is not None:
                p["include"] = ov["include"]
            done["n"] += 1
            self.app.after(0, lambda k=done["n"]: self.progress.configure(text=f"불러오는 중 {k}/{len(codes)}", text_color=TEXT_SECONDARY))
            return p

        # 피어 4개씩 동시에 (DART·KRX 호출이 대부분 대기 시간이라 병렬이 잘 먹는다)
        with ThreadPoolExecutor(max_workers=4) as ex:
            peers = list(ex.map(one, codes))
        try:
            self.app.rates = kofia.market_rates(as_of, log=self.app.log)
        except Exception as e:
            self.app.log(f"금투협 조회 실패: {e}"); self.app.rates = None
        idx = []
        if self.app.krx_ok:
            try:
                s, e = md.window_for(as_of)
                idx = self.app.fetchers["index"](s, e)
                pipeline.compute_betas(peers, idx, as_of)
            except Exception as e:
                self.app.log(f"지수 조회 실패: {e}")
        self.app.peers_loaded, self.app.index_daily = peers, idx
        self.app.after(0, self._after_load)

    def _after_load(self):
        self.load_btn.configure(state="normal")
        self.report_btn.configure(state="normal")
        n_ok = sum(1 for p in self.app.peers_loaded if p["status"] == "ok")
        self.progress.configure(text=f"완료 — 정상 {n_ok} / 전체 {len(self.app.peers_loaded)}", text_color=TEXT_SECONDARY)
        self.render()

    # ── 표 (ttk.Treeview) ────────────────────────────────────────────────
    _COLS = [("name", "회사명", 120, "w"), ("code", "코드", 60, "center"), ("close", "종가", 70, "e"), ("e", "E(억)", 80, "e"),
             ("d", "D(억)", 70, "e"), ("de", "D/E", 64, "e"), ("tax", "세율", 52, "e"), ("raw", "β raw", 64, "e"),
             ("blume", "β Blume", 68, "e"), ("n", "n", 40, "e"), ("r2", "R²", 52, "e"), ("kraw", "한공회 실질", 80, "e"),
             ("kadj", "한공회 조정", 80, "e"), ("kpts", "포인트", 52, "e"), ("diff", "차이", 60, "e"), ("bl", "βL 적용", 66, "e"),
             ("bu", "βU", 64, "e"), ("inc", "집계", 44, "center"), ("debt", "부채", 52, "center"), ("flags", "상태/플래그", 260, "w")]

    def _build_table(self, parent):
        box = ctk.CTkFrame(parent, fg_color=ui_theme.SURFACE, corner_radius=0)
        box.grid(row=2, column=0, sticky="nsew", padx=6, pady=4)
        box.grid_columnconfigure(0, weight=1); box.grid_rowconfigure(0, weight=1)
        st = ttk.Style()
        st.configure("Sum.Treeview", font=(ui_theme.FONT_FAMILY, 10), rowheight=26, borderwidth=0, background=ui_theme.SURFACE, fieldbackground=ui_theme.SURFACE)
        st.configure("Sum.Treeview.Heading", font=(ui_theme.FONT_FAMILY, 10, "bold"), background=ui_theme.HEADER_FILL,
                     foreground=ui_theme.HEADER_TEXT, relief="flat", padding=(4, 6))
        st.map("Sum.Treeview.Heading", background=[("active", ui_theme.HEADER_FILL)])
        st.map("Sum.Treeview", background=[("selected", ui_theme.SURFACE)], foreground=[("selected", ui_theme.TEXT_PRIMARY)])
        self.tree = ttk.Treeview(box, columns=[c[0] for c in self._COLS], show="headings", style="Sum.Treeview", selectmode="none")
        for key, title, width, anchor in self._COLS:
            self.tree.heading(key, text=title, anchor="center")
            self.tree.column(key, width=width, minwidth=30, anchor=anchor, stretch=(key == "flags"))
        self.tree.tag_configure("odd", background=ui_theme.ROW_STRIPE)
        self.tree.tag_configure("out", foreground=TEXT_SECONDARY)
        self.tree.tag_configure("flag", foreground=NEGATIVE)
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); vs.grid(row=0, column=1, sticky="ns"); hs.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.empty_label = ctk.CTkLabel(box, text="후보군 탭에서 피어를 선택한 뒤 [피어 자료 불러오기]를 누르세요.", text_color=TEXT_SECONDARY)

    def _on_tree_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        key = self._COLS[int(self.tree.identify_column(event.x)[1:]) - 1][0]
        code = self.tree.identify_row(event.y)
        if not code:
            return
        if key == "inc":
            self.include_vars[code] = not self.include_vars.get(code, False)
            self._on_include(code)
        elif key == "debt":
            self.open_debt_detail(code)

    def render(self):
        self.tree.delete(*self.tree.get_children())
        self.include_vars = {}
        s = self.app.sess
        if not self.app.peers_loaded:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
            self.agg_label.configure(text="집계 없음")
            return
        self.empty_label.place_forget()
        rows, agg = pipeline.summarize(self.app.peers_loaded, beta_source=s["beta_source"],
                                       de_method=s["de_method"], tax_target=s["tax_target"],
                                       include_lease=bool(s.get("include_lease", True)))
        self.rows = rows
        for i, r in enumerate(rows):
            diff = (r["kicpa_adj"] - r["beta_blume"]) if (r["kicpa_adj"] is not None and r["beta_blume"] is not None) else None
            flag_txt = ((r["status"] if r["status"] != "ok" else "") + " " + ", ".join(r["flags"])).strip()
            vals = (r["name"], r["code"], _f(r["close"], "{:,.0f}"), _f(r["e"] / 1e8 if r["e"] else None, "{:,.0f}"),
                    _f(r["d"] / 1e8 if r["d"] is not None else None, "{:,.0f}"), _f(r["de"]), _f(r["tax"], "{:.1%}"),
                    _f(r["beta_raw"]), _f(r["beta_blume"]), _f(r["beta_n"], "{}"), _f(r["beta_r2"]),
                    _f(r["kicpa_raw"], "{:.6f}"), _f(r["kicpa_adj"], "{:.6f}"), _f(r["kicpa_points"], "{}"), _f(diff),
                    _f(r["beta_l_used"]), _f(r["beta_u"]), "☑" if r["include"] else "☐", "상세…", flag_txt)
            self.include_vars[r["code"]] = bool(r["include"])
            tags = (["odd"] if i % 2 else []) + ([] if r["include"] else ["out"]) + (["flag"] if r["flags"] else [])
            self.tree.insert("", "end", iid=r["code"], values=vals, tags=tags)
        src = "한공회 조정β" if s["beta_source"] == "kicpa" else "산출 Blume β"
        how = "중앙값" if s["de_method"] == "median" else "평균"
        lease = "리스 포함" if s.get("include_lease", True) else "리스 제외"
        rt = getattr(self.app, "rates", None) or {}
        rate_txt = (f"\n금투협 {rt.get('date_used')}: Rf 국고10년 {rt.get('ktb10_final') or rt.get('ktb10_val')}% · Kd BBB- 5년 {rt.get('bbb_minus_5y')}% (3년 {rt.get('bbb_minus_3y')}%) → WACC 시트에 자동 입력"
                    if rt else "")
        if agg["n"]:
            self.agg_label.configure(text=f"βU {how} {agg['beta_u']:.4f} · 목표 D/E {agg['de']:.4f} · 재레버 βL {agg['beta_l_target']:.4f}   (소스 {src}, {lease}, 집계 {agg['n']}개, 대상 세율 {s['tax_target']:.1%}){rate_txt}")
        else:
            self.agg_label.configure(text=f"집계 가능한 피어가 없습니다 (소스 {src})")

    def _on_include(self, code):
        v = bool(self.include_vars.get(code))
        for p in self.app.peers_loaded:
            if p["code"] == code:
                p["include"] = v
        self.app.sess["peer_overrides"].setdefault(code, {})["include"] = v
        self.render()

    # ── 부채 상세 (항목별 포함/제외) ─────────────────────────────────────
    def open_debt_detail(self, code):
        p = next((x for x in self.app.peers_loaded if x["code"] == code), None)
        if not p or not p.get("liab_items"):
            self.progress.configure(text="부채 상세가 없습니다 (DART 재무 미조회).", text_color=NEGATIVE)
            return
        win = ctk.CTkToplevel(self.frame)
        win.title(f"이자부부채 항목 — {p['name']} ({p.get('report_label', '')})")
        win.geometry("640x520")
        win.grab_set()
        body = ui_theme.ScrollFrame(win)
        body.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        table_header(body, "포함", width=44, row=0, column=0)
        table_header(body, "계정명", width=300, row=0, column=1)
        table_header(body, "금액(백만원)", width=120, anchor="e", row=0, column=2)
        table_header(body, "규칙", width=60, row=0, column=3)
        vars_ = {}
        for i, it in enumerate(p["liab_items"], 1):
            bg = zebra_bg(i)
            v = tk.BooleanVar(value=bool(it.get("include", it["default"])))
            vars_[it["name"]] = v
            tk.Checkbutton(body, variable=v, bg=bg, activebackground=bg, bd=0, highlightthickness=0).grid(row=i, column=0, sticky="ew")
            table_cell(body, it["name"], bg=bg, row=i, column=1, padx=4)
            table_cell(body, f"{it['amount'] / 1e6:,.0f}", bg=bg, anchor="e", row=i, column=2, padx=4)
            table_cell(body, "포함" if it["default"] else "—", bg=bg, fg=TEXT_SECONDARY, row=i, column=3, padx=4)
        foot = ctk.CTkFrame(win, fg_color="transparent")
        foot.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(foot, text="규칙 = 계정명에 차입금·사채·리스부채·유동성장기부채. 금융부채 등은 주석을 보고 직접 판단.",
                     text_color=TEXT_SECONDARY, anchor="w").pack(side="left")

        def apply():
            sel = {k: v.get() for k, v in vars_.items()}
            pipeline.apply_debt_selection(p, sel)
            self.app.sess["peer_overrides"].setdefault(code, {})["debt_include"] = sel
            win.destroy()
            self.render()
        ctk.CTkButton(foot, text="적용", width=80, command=apply).pack(side="right")

    # ── 보고서 ──────────────────────────────────────────────────────────
    def make_report(self):
        s = self.app.candidate_panel.collect_session()
        name = s["target"]["name"] or "대상"
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        path = os.path.join(DOWNLOADS_DIR, f"WACC피어_{name}_{s['as_of']}.xlsx")
        window = md.window_for(s["as_of"])
        notes = []
        if not self.app.krx_ok:
            notes.append("KRX 미로그인 상태로 생성 — 산출 베타 없음, 시총은 한공회 종가 기준.")
        data = pipeline.build_report_data(s, self.app.candidate_panel.candidates_for_report(), self.app.peers_loaded,
                                          self.app.index_daily, dt.date.today().isoformat(), window, notes,
                                          rates=getattr(self.app, "rates", None))
        self.report_btn.configure(state="disabled")
        self.result_label.configure(text="보고서 생성 중… (Excel 계산값 저장 포함, 5~10초)", text_color=TEXT_SECONDARY)

        def run():
            try:
                saved, _ = report.build(data, path, recalc=True)
            except Exception as e:
                self.app.after(0, lambda: self.result_label.configure(text=f"보고서 생성 실패: {e}", text_color=NEGATIVE))
                self.app.after(0, lambda: self.report_btn.configure(state="normal"))
                return
            def done():
                self.report_btn.configure(state="normal")
                self.result_label.configure(text=f"저장: {saved}", text_color=TEXT_SECONDARY)
                try:
                    os.startfile(saved)
                except OSError:
                    pass
            self.app.after(0, done)
        threading.Thread(target=run, daemon=True).start()
