"""peer_wacc 진입점: 창 셸, 설정, 시작 시 KIND 목록·KRX 로그인(백그라운드)."""
import datetime as dt
import os
import threading
import tkinter as tk

import customtkinter as ctk

import dart_inputs
import market_data as md
import pipeline
import session as sess_mod
import settings
import ui_theme
from candidate_panel import CandidatePanel, default_as_of
from summary_panel import SummaryPanel


class PeerApp(ctk.CTk):
    def __init__(self):
        ui_theme.apply_theme()
        super().__init__()
        self.configure(fg_color=ui_theme.WINDOW_BG)
        self.title("동종기업 · WACC 베타/목표부채비율")
        self.geometry("1420x780")
        self.minsize(1100, 600)

        settings.ensure_dirs()
        self.cfg = settings.load_config()
        self.api_key = self.cfg.get("dart_api_key", "")
        self.fetchers = pipeline.default_fetchers(self.api_key)
        self.krx_ok = False
        self.dart_state = "확인 중"
        self.sess = sess_mod.new("", default_as_of())
        self.kind_rows, self.candidates, self.peers_loaded, self.index_daily = [], [], [], []
        self.kicpa, self.caps, self.rates, self.fin_brief = {}, {}, None, {}

        self._build_ui()
        ui_theme.apply_titlebar_theme(self)
        kp = self.cfg.get("kicpa_path")
        if kp and os.path.exists(kp):                  # 마지막으로 연 한공회 베타 파일 자동 로드 (UI 스레드)
            self.after(0, lambda: self.summary_panel._load_kicpa(kp))
        threading.Thread(target=self._startup, daemon=True).start()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        top.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(top, text="시작 중…", anchor="w", text_color=ui_theme.TEXT_SECONDARY)
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.env_label = ctk.CTkLabel(top, text="", anchor="e", text_color=ui_theme.TEXT_SECONDARY)
        self.env_label.grid(row=0, column=1, sticky="e", padx=(8, 8))
        ctk.CTkButton(top, text="설정", width=60, command=self._open_settings).grid(row=0, column=2)

        # 후보군 / 요약 을 탭으로 — 한 화면에 다 넣으면 열이 잘려서 보기 어렵다
        self.tabs = ctk.CTkTabview(self, fg_color=ui_theme.WINDOW_BG, segmented_button_selected_color=ui_theme.ACCENT,
                                   segmented_button_unselected_color=ui_theme.ACCENT_SOFT, segmented_button_selected_hover_color=ui_theme.ACCENT_HOVER)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
        t1, t2 = self.tabs.add("1. 후보군"), self.tabs.add("2. 요약 · WACC")
        for t in (t1, t2):
            t.grid_columnconfigure(0, weight=1); t.grid_rowconfigure(0, weight=1)
        self.candidate_panel = CandidatePanel(t1, self)
        self.candidate_panel.frame.grid(row=0, column=0, sticky="nsew")
        self.summary_panel = SummaryPanel(t2, self)
        self.summary_panel.frame.grid(row=0, column=0, sticky="nsew")

    def show_summary(self):
        self.tabs.set("2. 요약 · WACC")

    def reset(self):
        """새 작업 시작 — 후보·선택·피어·조회 캐시·메시지를 비운다. 상장사 목록·설정·한공회 파일은 유지."""
        self.sess = sess_mod.new("", default_as_of())
        self.candidates, self.peers_loaded, self.index_daily = [], [], []
        self.rates, self.fin_brief = None, {}
        self.candidate_panel.reset()
        self.summary_panel.reset()
        self.set_status("초기화 완료 — 새 작업을 시작하세요. (상장사 목록·설정·한공회 파일은 유지)")

    # ── 공용 ────────────────────────────────────────────────────────────
    def ui(self, fn, *args):
        self.after(0, lambda: fn(*args))

    def log(self, msg):
        print(f"[{dt.datetime.now():%H:%M:%S}] {msg}")

    def set_status(self, text):
        self.after(0, lambda: self.status_label.configure(text=text))

    def _env_text(self):
        return f"DART 키 {self.dart_state} · KRX {'로그인 ✔' if self.krx_ok else '미로그인 ✘'}"

    def _check_dart_key(self):
        """키 검증 결과를 dart_state에 둔다. 키는 이 앱의 config.txt에서만 읽는다."""
        ok, msg = dart_inputs.check_key(self.api_key)
        self.dart_state = "✔" if ok else f"✘ {msg}"

    # ── 시작 시 백그라운드 ───────────────────────────────────────────────
    def _startup(self):
        try:
            rows = md.load_kind_list()
            self.kind_rows = rows
            self.ui(self.candidate_panel.set_industries, rows)
            self.set_status(f"상장사 목록 {len(rows):,}개 로드 ({dt.date.today()})")
        except Exception as e:
            self.set_status(f"상장사 목록 로드 실패: {e}")
        self._check_dart_key()
        self.krx_ok = md.krx_login(self.cfg["krx_id"], self.cfg["krx_pw"])
        self.after(0, lambda: self.env_label.configure(text=self._env_text()))
        if not self.krx_ok:
            self.set_status(md.last_error)
            self.ui(self.summary_panel.force_kicpa_source)
        else:
            # 전종목 시총(2,800개)은 시총 필터를 실제로 쓸 때만 받는다(candidate_panel.ensure_caps)
            # 예열: 첫 KRX 시세 호출에 딸려오는 ISIN 표 다운로드(~10초)와 KOSPI 2년을 미리 받아 둔다
            try:
                s, e = md.window_for(self.sess["as_of"])
                md.index_closes(s, e)
                self.set_status(f"준비 완료 — 상장사 {len(self.kind_rows):,}개 · KRX 예열 끝")
            except Exception as e:
                self.log(f"KRX 예열 실패: {e}")

    # ── 설정 ────────────────────────────────────────────────────────────
    def _open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("설정")
        win.geometry("520x220")
        win.grab_set()
        vars_ = {}
        for i, (k, label, show) in enumerate([("dart_api_key", "DART 인증키", ""), ("krx_id", "KRX 아이디", ""), ("krx_pw", "KRX 비밀번호", "*")]):
            ctk.CTkLabel(win, text=label).grid(row=i, column=0, sticky="w", padx=12, pady=8)
            v = tk.StringVar(value=self.cfg.get(k, ""))
            vars_[k] = v
            ctk.CTkEntry(win, textvariable=v, width=340, show=show).grid(row=i, column=1, padx=8)
        def save():
            self.cfg = {k: v.get().strip() for k, v in vars_.items()}
            settings.save_config(self.cfg)
            self.api_key = self.cfg.get("dart_api_key", "")
            self.fetchers = pipeline.default_fetchers(self.api_key)
            win.destroy()
            threading.Thread(target=self._relogin, daemon=True).start()
        ctk.CTkButton(win, text="저장", command=save).grid(row=3, column=1, sticky="e", padx=8, pady=12)

    def _relogin(self):
        self._check_dart_key()
        self.krx_ok = md.krx_login(self.cfg["krx_id"], self.cfg["krx_pw"])
        self.after(0, lambda: self.env_label.configure(text=self._env_text()))
        self.set_status("KRX 로그인 성공" if self.krx_ok else md.last_error)


def main():
    PeerApp().mainloop()


if __name__ == "__main__":
    main()
