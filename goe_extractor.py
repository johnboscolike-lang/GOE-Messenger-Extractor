# -*- coding: utf-8 -*-
"""
GOE메신저 추출기 v3.0 — Windows Desktop App
HTML v3 디자인 재현: 사이드바 필터 + 탭 + 내보내기 카드
"""

import os, sys, re, csv, glob, hashlib, sqlite3, tempfile, threading
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from Crypto.Cipher import AES
import customtkinter as ctk
from tkinter import filedialog, messagebox

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ── 상수 ──
APP_NAME = "GOE 추출기"
APP_VERSION = "v3.0"
DEFAULT_EXPORT_DIR = str(Path.home() / "Documents" / "GOE메신저_Exports")
DB_SEARCH_PATHS = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "AtMessenger"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "AtMessenger7"),
    os.path.join(os.environ.get("APPDATA", ""), "AtMessenger"),
    os.path.join(os.environ.get("APPDATA", ""), "AtMessenger7"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "GOEMessenger"),
]
DB_FILE_PATTERNS = ["@Talk.db", "Talk.db", "*.db"]
PAGE_SIZE = 1024; RESERVE_SIZE = 48; SALT_SIZE = 16
DECRYPT_PASSWORD = b"49100hsy"; KDF_ITER = 64000
SQLITE_HEADER = b"SQLite format 3\x00"

# 색상
C = {
    "primary": "#2563eb", "primary_hover": "#1d4ed8", "primary_light": "#dbeafe",
    "primary_50": "#eff6ff", "accent": "#7c3aed", "accent_light": "#ede9fe",
    "success": "#059669", "success_light": "#d1fae5",
    "warning": "#d97706", "warning_light": "#fef3c7",
    "danger": "#dc2626", "danger_light": "#fee2e2",
    "bg": "#f1f5f9", "surface": "#ffffff", "sidebar": "#f8fafc",
    "border": "#e2e8f0", "text": "#1e293b", "text_sec": "#64748b",
    "text_muted": "#94a3b8", "header": "#0f172a",
}


# ══════════════════════════════════════════════
# 유틸리티 & DB
# ══════════════════════════════════════════════

def decrypt_db(src_path, progress_cb=None):
    with open(src_path, "rb") as f:
        header = f.read(16)
    if header[:16] == SQLITE_HEADER:
        return src_path
    with open(src_path, "rb") as f:
        data = f.read()
    if len(data) < PAGE_SIZE or len(data) % PAGE_SIZE != 0:
        raise ValueError("올바른 GOE메신저 DB/백업 파일이 아닙니다")
    if progress_cb: progress_cb("암호화 키 생성 중 (PBKDF2)...")
    salt = data[:SALT_SIZE]
    key = hashlib.pbkdf2_hmac("sha1", DECRYPT_PASSWORD, salt, KDF_ITER, dklen=32)
    page_count = len(data) // PAGE_SIZE
    out = bytearray(len(data))
    if progress_cb: progress_cb(f"복호화 중... ({page_count:,}페이지)")
    for i in range(page_count):
        off = i * PAGE_SIZE
        page = data[off:off + PAGE_SIZE]
        es = SALT_SIZE if i == 0 else 0
        enc = page[es:PAGE_SIZE - RESERVE_SIZE]
        iv = page[PAGE_SIZE - RESERVE_SIZE:PAGE_SIZE - RESERVE_SIZE + 16]
        dec = AES.new(key, AES.MODE_CBC, iv).decrypt(enc)
        if i == 0:
            out[0:16] = SQLITE_HEADER
            out[SALT_SIZE:SALT_SIZE + len(dec)] = dec
        else:
            out[off:off + len(dec)] = dec
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, prefix="goe_dec_")
    tmp.write(out); tmp.close()
    if progress_cb: progress_cb("복호화 완료!")
    return tmp.name

def find_talk_db():
    found = []
    for base in DB_SEARCH_PATHS:
        if not base or not os.path.isdir(base): continue
        for pat in DB_FILE_PATTERNS:
            for m in glob.glob(os.path.join(base, pat)):
                if os.path.isfile(m) and os.path.getsize(m) > 1024: found.append(m)
        try:
            for sub in os.listdir(base):
                sd = os.path.join(base, sub)
                if os.path.isdir(sd):
                    for pat in DB_FILE_PATTERNS:
                        for m in glob.glob(os.path.join(sd, pat)):
                            if os.path.isfile(m) and os.path.getsize(m) > 1024: found.append(m)
        except PermissionError: pass
    seen = set(); unique = []
    for f in found:
        n = os.path.normpath(f)
        if n not in seen: seen.add(n); unique.append(n)
    unique.sort(key=lambda f: os.path.getsize(f), reverse=True)
    return unique

def fmt_size(b):
    return f"{b/1024:.1f}KB" if b < 1024*1024 else f"{b/(1024*1024):.1f}MB"

def fmt_date(raw):
    if not raw: return ""
    s = str(raw).strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}" if len(s) >= 14 and s[:4].isdigit() else s

def clean_content(text):
    if not text: return ""
    idx = text.find("{RTF}")
    return text[:idx].strip() if idx != -1 else text


class DBReader:
    def __init__(self, path):
        self.db_path = path; self.conn = None; self.tables = []; self._dec = None

    def connect(self, cb=None):
        actual = decrypt_db(self.db_path, cb)
        if actual != self.db_path: self._dec = actual
        self.conn = sqlite3.connect(actual, check_same_thread=False)
        self.conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        self.tables = [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    def close(self):
        if self.conn: self.conn.close()
        if self._dec and os.path.exists(self._dec):
            try: os.unlink(self._dec)
            except: pass

    def has(self, t): return t in self.tables
    def _ct(self): return "tblChatContent" if self.has("tblChatContent") else "tblChatMessage"
    def _rt(self): return "tblChatRoomInfo" if self.has("tblChatRoomInfo") else "tblChatRoom"

    def date_range(self):
        if not self.has("tblMessage"): return None, None
        try:
            r = self.conn.execute("SELECT MIN(sDate),MAX(sDate) FROM tblMessage WHERE sDate IS NOT NULL AND sDate!=''").fetchone()
            if r and r[0] and r[1]: return fmt_date(r[0])[:10], fmt_date(r[1])[:10]
        except: pass
        return None, None

    def _dw(self, df, dt, depts=None):
        c = []
        if df: c.append(f"sDate>='{df.replace('-','')}000000'")
        if dt: c.append(f"sDate<='{dt.replace('-','')}235959'")
        if depts is not None:
            escaped = [d.replace("'", "''") for d in depts]
            if escaped:
                in_list = ",".join(f"'{d}'" for d in escaped)
                c.append(f"COALESCE(sSenderPart,'소속미상') IN ({in_list})")
            else:
                c.append("1=0")
        return ("WHERE " + " AND ".join(c)) if c else ""

    def counts(self, df=None, dt=None, depts=None):
        r = {}
        if self.has("tblMessage"):
            w = self._dw(df, dt, depts)
            rows = self.conn.execute(f"SELECT cIsSend,COUNT(*) FROM tblMessage {w} GROUP BY cIsSend").fetchall()
            s = v = 0
            for row in rows:
                if row[0] == "Y": s = row[1]
                else: v = row[1]
            r["sent"], r["recv"], r["all"] = s, v, s + v
        ct = self._ct()
        if self.has(ct):
            try: r["chat"] = self.conn.execute(f"SELECT COUNT(*) FROM {ct}").fetchone()[0]
            except: r["chat"] = 0
        rt = self._rt()
        if self.has(rt):
            try: r["room"] = self.conn.execute(f"SELECT COUNT(*) FROM {rt}").fetchone()[0]
            except: r["room"] = 0
        return r

    def departments(self, df=None, dt=None):
        if not self.has("tblMessage"): return []
        w = self._dw(df, dt)
        return [(r[0] or "소속미상", r[1]) for r in
                self.conn.execute(f"SELECT sSenderPart,COUNT(*) FROM tblMessage {w} GROUP BY sSenderPart ORDER BY COUNT(*) DESC").fetchall()]

    def senders(self, df=None, dt=None, depts=None):
        if not self.has("tblMessage"): return []
        w = self._dw(df, dt, depts)
        w2 = (w + " AND cIsSend!='Y'") if w else "WHERE cIsSend!='Y'"
        return [(r[0] or "이름없음", r[1] or "", r[2]) for r in
                self.conn.execute(f"SELECT sSenderName,sSenderPart,COUNT(*) FROM tblMessage {w2} GROUP BY sSenderName ORDER BY COUNT(*) DESC").fetchall()]

    def receivers(self, df=None, dt=None):
        """발신 수신자별 — 보낸 쪽지의 수신자 기준"""
        if not self.has("tblMessage"): return []
        w = self._dw(df, dt)
        w2 = (w + " AND cIsSend='Y'") if w else "WHERE cIsSend='Y'"
        rows = self.conn.execute(f"SELECT sReceiverNames FROM tblMessage {w2}").fetchall()
        counter = defaultdict(int)
        for r in rows:
            if r[0]:
                for name in r[0].split(","):
                    name = name.strip()
                    if name: counter[name] += 1
        return sorted(counter.items(), key=lambda x: -x[1])

    def notes(self, df=None, dt=None, direction="all"):
        if not self.has("tblMessage"): return []
        w = self._dw(df, dt)
        if direction == "sent": w += (" AND " if "WHERE" in w else "WHERE ") + "cIsSend='Y'"
        elif direction == "recv": w += (" AND " if "WHERE" in w else "WHERE ") + "cIsSend!='Y'"
        NF = ["메시지ID","보낸사람","소속","날짜","발신여부","제목","내용","수신자","첨부파일"]
        rows = []
        for r in self.conn.execute(f"SELECT sMsgId,sSenderName,sSenderPart,sDate,cIsSend,sSubject,sContent,sReceiverNames,sAttach FROM tblMessage {w} ORDER BY sDate DESC").fetchall():
            rows.append(dict(zip(NF, [r[0] or "", r[1] or "", r[2] or "", fmt_date(r[3]),
                                       "발신" if r[4] == "Y" else "수신", r[5] or "",
                                       clean_content(r[6] or ""), r[7] or "", r[8] or ""])))
        return rows

    def chat_msgs(self):
        t = self._ct()
        if not self.has(t): return []
        cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({t})").fetchall()]
        return [dict(zip(cols, r)) for r in self.conn.execute(f"SELECT * FROM {t} ORDER BY rowid DESC").fetchall()]

    def chat_rooms(self):
        t = self._rt()
        if not self.has(t): return []
        cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({t})").fetchall()]
        return [dict(zip(cols, r)) for r in self.conn.execute(f"SELECT * FROM {t}").fetchall()]


def write_csv(fp, rows, fields=None):
    if not rows: return 0
    if not fields: fields = list(rows[0].keys())
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for r in rows: w.writerow(r)
    return len(rows)


# ══════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════

NOTE_FIELDS = ["메시지ID","보낸사람","소속","날짜","발신여부","제목","내용","수신자","첨부파일"]

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1100x760")
        self.minsize(950, 650)
        self.configure(fg_color=C["bg"])

        self.db: DBReader = None
        self.stats = {}
        self.depts = []
        self.processing = False
        self.export_dir = DEFAULT_EXPORT_DIR

        self._build()
        self.after(300, self._auto_detect)

    # ────────────────────────────────
    # Build UI
    # ────────────────────────────────
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ═══ TOP BAR ═══
        top = ctk.CTkFrame(self, height=48, fg_color=C["header"], corner_radius=0)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_columnconfigure(2, weight=1)
        top.grid_propagate(False)

        # Logo
        logo = ctk.CTkFrame(top, width=32, height=32, corner_radius=8, fg_color=C["primary"])
        logo.grid(row=0, column=0, padx=(14, 6), pady=8)
        logo.grid_propagate(False)
        ctk.CTkLabel(logo, text="G", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="white").place(relx=.5, rely=.5, anchor="center")
        ctk.CTkLabel(top, text=APP_NAME, font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="white").grid(row=0, column=1, padx=(0, 8), pady=8)

        # Spacer
        ctk.CTkLabel(top, text="", fg_color="transparent").grid(row=0, column=2)

        # Stats badges (right side)
        self.badge_total = self._badge(top, "전체 0건", C["primary_light"], C["primary"])
        self.badge_total.grid(row=0, column=3, padx=3, pady=8)

        self.badge_decrypt = self._badge(top, "백업 복호화", C["danger_light"], C["danger"])
        self.badge_decrypt.grid(row=0, column=4, padx=3, pady=8)

        self.badge_type = self._badge(top, "쪽지+대화방", C["warning_light"], C["warning"])
        self.badge_type.grid(row=0, column=5, padx=3, pady=8)

        ctk.CTkButton(top, text="다른 파일", width=70, height=28,
                      font=ctk.CTkFont(size=11), fg_color=C["text_sec"],
                      hover_color=C["text_muted"], corner_radius=6,
                      command=self._browse_db).grid(row=0, column=6, padx=(3, 14), pady=8)

        # ═══ LEFT SIDEBAR ═══
        sidebar = ctk.CTkScrollableFrame(self, width=260, fg_color=C["surface"],
                                          corner_radius=0, border_width=0)
        sidebar.grid(row=1, column=0, sticky="nsew")
        self.sidebar = sidebar

        # Filter header
        fh = ctk.CTkFrame(sidebar, fg_color="transparent")
        fh.pack(fill="x", padx=14, pady=(12, 8))
        ctk.CTkLabel(fh, text="필터", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(fh, text="초기화", width=40, height=20, font=ctk.CTkFont(size=10),
                      fg_color="transparent", hover_color=C["primary_light"],
                      text_color=C["primary"], command=self._reset_filters
                      ).pack(side="right")

        # ── 날짜 필터 ──
        self._section_header(sidebar, "날짜")
        date_sec = ctk.CTkFrame(sidebar, fg_color="transparent")
        date_sec.pack(fill="x", padx=14, pady=(0, 8))

        # Quick buttons
        qf = ctk.CTkFrame(date_sec, fg_color="transparent")
        qf.pack(fill="x", pady=(0, 6))
        self.date_quick_var = ctk.StringVar(value="전체")
        for txt in ["전체", "올해", "6개월", "1개월"]:
            b = ctk.CTkButton(qf, text=txt, width=52, height=24,
                              font=ctk.CTkFont(size=10),
                              fg_color=C["primary"] if txt == "전체" else C["surface"],
                              text_color="white" if txt == "전체" else C["text_sec"],
                              hover_color=C["primary_light"],
                              border_width=1, border_color=C["border"], corner_radius=12,
                              command=lambda t=txt: self._set_date_quick(t))
            b.pack(side="left", padx=(0, 3))

        # Date range
        dr = ctk.CTkFrame(date_sec, fg_color="transparent")
        dr.pack(fill="x", pady=(0, 4))
        self.date_from = ctk.CTkEntry(dr, width=100, height=26, placeholder_text="년-월-일",
                                       font=ctk.CTkFont(size=10), corner_radius=4)
        self.date_from.pack(side="left")
        ctk.CTkLabel(dr, text=" ~ ", font=ctk.CTkFont(size=10), text_color=C["text_muted"]).pack(side="left")
        self.date_to = ctk.CTkEntry(dr, width=100, height=26, placeholder_text="년-월-일",
                                     font=ctk.CTkFont(size=10), corner_radius=4)
        self.date_to.pack(side="left")

        # ── 필터 적용 버튼 ──
        self.apply_btn = ctk.CTkButton(
            sidebar, text="필터 적용", height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=C["primary"], hover_color=C["primary_hover"], corner_radius=8,
            command=self._apply_filters
        )
        self.apply_btn.pack(fill="x", padx=14, pady=(6, 4))

        # 필터 상태 표시
        self.filter_status = ctk.CTkLabel(sidebar, text="",
                                           font=ctk.CTkFont(size=10), text_color=C["success"],
                                           wraplength=220)
        self.filter_status.pack(anchor="w", padx=14, pady=(0, 4))

        self._sep(sidebar)

        # ── 부서/소속 ──
        dept_hdr = ctk.CTkFrame(sidebar, fg_color="transparent")
        dept_hdr.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(dept_hdr, text="부서/소속", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        self.dept_count_badge = ctk.CTkLabel(dept_hdr, text="0",
                                              font=ctk.CTkFont(size=9, weight="bold"),
                                              text_color="white", fg_color=C["primary"],
                                              corner_radius=8, width=24, height=18)
        self.dept_count_badge.pack(side="left", padx=6)

        self.dept_search = ctk.CTkEntry(sidebar, height=26, placeholder_text="부서 검색...",
                                         font=ctk.CTkFont(size=10), corner_radius=4)
        self.dept_search.pack(fill="x", padx=14, pady=(0, 4))

        self.dept_scroll = ctk.CTkScrollableFrame(sidebar, height=130, fg_color=C["bg"],
                                                    corner_radius=6)
        self.dept_scroll.pack(fill="x", padx=14, pady=(0, 8))
        self.dept_checks = {}

        self._sep(sidebar)

        # ── 첨부파일 ──
        self._section_header(sidebar, "첨부파일")
        af = ctk.CTkFrame(sidebar, fg_color="transparent")
        af.pack(fill="x", padx=14, pady=(0, 8))
        self.attach_var = ctk.StringVar(value="전체")
        for txt in ["전체", "있음", "없음"]:
            ctk.CTkButton(af, text=txt, width=60, height=24,
                          font=ctk.CTkFont(size=10),
                          fg_color=C["primary"] if txt == "전체" else C["surface"],
                          text_color="white" if txt == "전체" else C["text_sec"],
                          hover_color=C["primary_light"],
                          border_width=1, border_color=C["border"], corner_radius=4,
                          command=lambda t=txt: self._set_toggle(self.attach_var, t, af)
                          ).pack(side="left", expand=True, fill="x", padx=1)

        self._sep(sidebar)

        # ── 발신/수신 ──
        self._section_header(sidebar, "발신/수신")
        df = ctk.CTkFrame(sidebar, fg_color="transparent")
        df.pack(fill="x", padx=14, pady=(0, 12))
        self.dir_var = ctk.StringVar(value="전체")
        for txt in ["전체", "수신", "발신"]:
            ctk.CTkButton(df, text=txt, width=60, height=24,
                          font=ctk.CTkFont(size=10),
                          fg_color=C["primary"] if txt == "전체" else C["surface"],
                          text_color="white" if txt == "전체" else C["text_sec"],
                          hover_color=C["primary_light"],
                          border_width=1, border_color=C["border"], corner_radius=4,
                          command=lambda t=txt: self._set_toggle(self.dir_var, t, df)
                          ).pack(side="left", expand=True, fill="x", padx=1)

        # ═══ MAIN CONTENT ═══
        main_frame = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main_frame.grid(row=1, column=1, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(2, weight=1)

        # Stats bar
        sbar = ctk.CTkFrame(main_frame, height=36, fg_color=C["surface"],
                             corner_radius=0, border_width=0)
        sbar.grid(row=0, column=0, sticky="ew")
        sbar.grid_propagate(False)
        sf = ctk.CTkFrame(sbar, fg_color="transparent")
        sf.pack(side="left", padx=16, pady=6)

        self.stat_labels = {}
        for key, label, color in [("shown", "표시", C["text_sec"]),
                                    ("all", "전체", C["text"]),
                                    ("sent", "발신", C["warning"]),
                                    ("recv", "수신", C["primary"]),
                                    ("people", "사람", C["accent"])]:
            f = ctk.CTkFrame(sf, fg_color="transparent")
            f.pack(side="left", padx=(0, 16))
            num = ctk.CTkLabel(f, text="0", font=ctk.CTkFont(size=14, weight="bold"),
                               text_color=color)
            num.pack(side="left")
            ctk.CTkLabel(f, text=f" {label}", font=ctk.CTkFont(size=10),
                         text_color=C["text_muted"]).pack(side="left")
            self.stat_labels[key] = num

        # Tabs
        tab_bar = ctk.CTkFrame(main_frame, height=38, fg_color=C["surface"],
                                corner_radius=0)
        tab_bar.grid(row=1, column=0, sticky="ew")
        tab_bar.grid_propagate(False)
        tf = ctk.CTkFrame(tab_bar, fg_color="transparent")
        tf.pack(side="left", padx=12, pady=0)

        self.tabs = {}
        self.tab_btns = {}
        self.current_tab = ctk.StringVar(value="쪽지함 전체")
        tab_names = ["쪽지함 전체", "받은 쪽지", "보낸 쪽지", "대화방 목록"]

        for name in tab_names:
            btn = ctk.CTkButton(tf, text=name, height=36,
                                font=ctk.CTkFont(size=11, weight="bold"),
                                fg_color="transparent", hover_color=C["bg"],
                                text_color=C["text_muted"], corner_radius=0,
                                command=lambda n=name: self._switch_tab(n))
            btn.pack(side="left", padx=0)
            self.tab_btns[name] = btn

        # Tab content area
        self.content_area = ctk.CTkScrollableFrame(main_frame, fg_color=C["bg"], corner_radius=0)
        self.content_area.grid(row=2, column=0, sticky="nsew")
        self.content_area.grid_columnconfigure(0, weight=1)

        # Log bar at bottom
        self.log_bar = ctk.CTkLabel(main_frame, text="", font=ctk.CTkFont(size=10),
                                     text_color=C["text_muted"], fg_color=C["surface"],
                                     height=24, anchor="w")
        self.log_bar.grid(row=3, column=0, sticky="ew")

        self._switch_tab("쪽지함 전체")

    # ── UI Helpers ──
    def _badge(self, parent, text, bg, fg):
        return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=10, weight="bold"),
                            text_color=fg, fg_color=bg, corner_radius=10,
                            height=24, padx=10)

    def _section_header(self, parent, title):
        ctk.CTkLabel(parent, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C["text"]).pack(anchor="w", padx=14, pady=(8, 4))

    def _sep(self, parent):
        ctk.CTkFrame(parent, height=1, fg_color=C["border"]).pack(fill="x", padx=14, pady=4)

    def _set_toggle(self, var, val, container):
        var.set(val)
        for w in container.winfo_children():
            if isinstance(w, ctk.CTkButton):
                active = w.cget("text") == val
                w.configure(
                    fg_color=C["primary"] if active else C["surface"],
                    text_color="white" if active else C["text_sec"]
                )
        self._apply_filters()

    def _set_date_quick(self, txt):
        self.date_quick_var.set(txt)
        # Update button colors
        for w in self.date_from.master.master.winfo_children():
            if isinstance(w, ctk.CTkFrame):
                for b in w.winfo_children():
                    if isinstance(b, ctk.CTkButton):
                        active = b.cget("text") == txt
                        b.configure(
                            fg_color=C["primary"] if active else C["surface"],
                            text_color="white" if active else C["text_sec"]
                        )
        now = datetime.now()
        if txt == "전체":
            self.date_from.delete(0, "end"); self.date_to.delete(0, "end")
            if self.date_min:
                self.date_from.insert(0, self.date_min)
                self.date_to.insert(0, self.date_max)
        elif txt == "올해":
            self.date_from.delete(0, "end"); self.date_from.insert(0, f"{now.year}-01-01")
            self.date_to.delete(0, "end"); self.date_to.insert(0, now.strftime("%Y-%m-%d"))
        elif txt == "6개월":
            d = now - timedelta(days=180)
            self.date_from.delete(0, "end"); self.date_from.insert(0, d.strftime("%Y-%m-%d"))
            self.date_to.delete(0, "end"); self.date_to.insert(0, now.strftime("%Y-%m-%d"))
        elif txt == "1개월":
            d = now - timedelta(days=30)
            self.date_from.delete(0, "end"); self.date_from.insert(0, d.strftime("%Y-%m-%d"))
            self.date_to.delete(0, "end"); self.date_to.insert(0, now.strftime("%Y-%m-%d"))
        self._apply_filters()

    def _apply_filters(self):
        """필터 적용: 스탯 갱신 + 부서 목록 갱신 + 현재 탭 새로고침"""
        if not self.db: return
        df, dt = self._get_dates()

        # 부서 목록을 현재 날짜 범위에 맞게 갱신
        self._populate_depts()

        # 스탯 갱신
        self._refresh_stats()

        # 현재 탭 내용 새로고침
        self._switch_tab(self.current_tab.get())

        # 필터 상태 표시
        parts = []
        if df or dt:
            parts.append(f"{df or '처음'}~{dt or '끝'}")
        if self.dir_var.get() != "전체":
            parts.append(self.dir_var.get())
        if self.attach_var.get() != "전체":
            parts.append(f"첨부 {self.attach_var.get()}")
        depts = self._get_selected_depts()
        if depts is not None:
            parts.append(f"부서 {len(depts)}개")
        if parts:
            self.filter_status.configure(
                text=f"적용됨: {', '.join(parts)}",
                text_color=C["warning"]
            )
        else:
            self.filter_status.configure(text="전체 데이터", text_color=C["success"])

        self._log(f"필터 적용 — 전체 {self.stats.get('all', 0):,}건")

    def _reset_filters(self):
        self.date_quick_var.set("전체")
        self.dir_var.set("전체")
        self.attach_var.set("전체")
        if self.date_min:
            self.date_from.delete(0, "end"); self.date_from.insert(0, self.date_min)
            self.date_to.delete(0, "end"); self.date_to.insert(0, self.date_max)
        # 모든 토글 버튼 UI 초기화
        for container_attr in [self.sidebar]:
            pass  # toggle UIs are reset via _apply_filters
        self._apply_filters()
        self.filter_status.configure(text="필터 초기화됨", text_color=C["success"])

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_bar.configure(text=f"  [{ts}] {msg}")

    # ── Tab System ──
    def _switch_tab(self, name):
        self.current_tab.set(name)
        for n, btn in self.tab_btns.items():
            if n == name:
                btn.configure(text_color=C["primary"],
                              fg_color="transparent")
            else:
                btn.configure(text_color=C["text_muted"],
                              fg_color="transparent")

        # Clear content
        for w in self.content_area.winfo_children():
            w.destroy()

        if not self.db:
            ctk.CTkLabel(self.content_area, text="자동 감지 중...",
                         font=ctk.CTkFont(size=14), text_color=C["text_muted"]).pack(pady=40)
            return

        if name == "쪽지함 전체":
            self._tab_all_notes()
        elif name == "받은 쪽지":
            self._tab_recv()
        elif name == "보낸 쪽지":
            self._tab_sent()
        elif name == "대화방 목록":
            self._tab_chatrooms()

    def _dl_card(self, parent, icon, title, desc, color, command):
        card = ctk.CTkFrame(parent, fg_color=C["surface"], corner_radius=10,
                            border_width=1, border_color=C["border"], cursor="hand2")
        card.pack(side="left", padx=(0, 8), pady=4)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(padx=14, pady=12)

        colors = {"blue": C["primary_light"], "green": C["success_light"],
                  "orange": C["warning_light"], "purple": C["accent_light"]}
        icon_bg = colors.get(color, C["primary_light"])

        ic = ctk.CTkFrame(inner, width=36, height=36, corner_radius=8, fg_color=icon_bg)
        ic.pack(side="left", padx=(0, 10))
        ic.pack_propagate(False)
        ctk.CTkLabel(ic, text=icon, font=ctk.CTkFont(size=16)).place(relx=.5, rely=.5, anchor="center")

        tf = ctk.CTkFrame(inner, fg_color="transparent")
        tf.pack(side="left")
        ctk.CTkLabel(tf, text=title, font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(tf, text=desc, font=ctk.CTkFont(size=9),
                     text_color=C["text_muted"]).pack(anchor="w")

        card.bind("<Button-1>", lambda e: command())
        for w in card.winfo_children():
            w.bind("<Button-1>", lambda e: command())
            for ww in w.winfo_children():
                ww.bind("<Button-1>", lambda e: command())
                for www in ww.winfo_children():
                    www.bind("<Button-1>", lambda e: command())

    def _get_dates(self):
        df = self.date_from.get().strip() or None
        dt = self.date_to.get().strip() or None
        return df, dt

    def _export_path(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        d = os.path.join(self.export_dir, f"GOE추출_{ts}")
        os.makedirs(d, exist_ok=True)
        return d

    # ── Tab: 쪽지함 전체 ──
    def _tab_all_notes(self):
        ctk.CTkLabel(self.content_area, text="전체 다운로드",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]
                     ).pack(anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(self.content_area, text="현재 필터가 적용된 상태의 쪽지를 다운로드합니다.",
                     font=ctk.CTkFont(size=11), text_color=C["text_sec"]
                     ).pack(anchor="w", padx=20, pady=(0, 10))

        row1 = ctk.CTkFrame(self.content_area, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(0, 8))
        self._dl_card(row1, "📦", "전체 ZIP 다운로드", "발신+수신 사람별 CSV 분리", "blue",
                      lambda: self._export_all_zip())
        self._dl_card(row1, "📄", "통합 CSV 1개", "모든 쪽지 한 파일로", "green",
                      lambda: self._export_single("all"))
        self._dl_card(row1, "🔍", "필터 적용 CSV", "현재 필터 결과만", "orange",
                      lambda: self._export_filtered())
        self._dl_card(row1, "🏢", "부서별 ZIP", "소속별로 CSV 분리", "purple",
                      lambda: self._export_by_dept())

        ctk.CTkLabel(self.content_area, text="기간별 다운로드",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]
                     ).pack(anchor="w", padx=20, pady=(12, 2))
        ctk.CTkLabel(self.content_area, text="연도/월별로 분리된 CSV를 다운로드합니다.",
                     font=ctk.CTkFont(size=11), text_color=C["text_sec"]
                     ).pack(anchor="w", padx=20, pady=(0, 10))

        row2 = ctk.CTkFrame(self.content_area, fg_color="transparent")
        row2.pack(fill="x", padx=20)
        self._dl_card(row2, "📅", "연도별 ZIP", "연도별 폴더 분리", "blue",
                      lambda: self._export_by_year())
        self._dl_card(row2, "📆", "월별 ZIP", "YYYY-MM 폴더 분리", "green",
                      lambda: self._export_by_month())

    # ── Tab: 받은 쪽지 (사람별 필터 포함) ──
    def _tab_recv(self):
        df, dt = self._get_dates()
        depts = self._get_selected_depts()
        senders = self.db.senders(df, dt, depts)

        # 헤더 + 필터 상태 표시
        header_frame = ctk.CTkFrame(self.content_area, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(16, 2))
        ctk.CTkLabel(header_frame, text="받은 쪽지",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]
                     ).pack(side="left")

        # 선택된 사람 수 / 전체 표시 배지
        self._recv_filter_badge = ctk.CTkLabel(
            header_frame, text=f"전체 {len(senders)}명 선택",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=C["primary"], fg_color=C["primary_light"],
            corner_radius=10, height=22, padx=10)
        self._recv_filter_badge.pack(side="left", padx=8)

        # 필터된 건수 표시
        self._recv_count_label = ctk.CTkLabel(
            header_frame, text="",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=C["success"])
        self._recv_count_label.pack(side="left", padx=4)

        ctk.CTkLabel(self.content_area,
                     text="보낸 사람을 체크하여 원하는 쪽지만 필터링하세요.",
                     font=ctk.CTkFont(size=11), text_color=C["primary"]
                     ).pack(anchor="w", padx=20, pady=(0, 8))

        # 다운로드 카드
        row = ctk.CTkFrame(self.content_area, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(0, 8))
        self._dl_card(row, "📥", "수신 CSV 다운로드", "선택된 사람의 받은 쪽지", "blue",
                      lambda: self._export_single("recv"))
        self._dl_card(row, "👥", "사람별 ZIP 다운로드", "선택된 사람별 개별 CSV", "purple",
                      lambda: self._export_by_person())

        # ── 사람 필터 영역 ──
        filter_box = ctk.CTkFrame(self.content_area, fg_color=C["surface"], corner_radius=8,
                                   border_width=1, border_color=C["border"])
        filter_box.pack(fill="x", padx=20, pady=(0, 12))

        # 전체선택/해제 버튼
        ctrl_row = ctk.CTkFrame(filter_box, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(ctrl_row, text=f"보낸 사람 ({len(senders)}명)",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=C["text"]).pack(side="left")
        ctk.CTkButton(ctrl_row, text="전체선택", width=55, height=20,
                      font=ctk.CTkFont(size=9), fg_color="transparent",
                      hover_color=C["primary_light"], text_color=C["primary"],
                      command=lambda: self._recv_sender_select_all(True)).pack(side="right", padx=2)
        ctk.CTkButton(ctrl_row, text="전체해제", width=55, height=20,
                      font=ctk.CTkFont(size=9), fg_color="transparent",
                      hover_color=C["danger_light"], text_color=C["danger"],
                      command=lambda: self._recv_sender_select_all(False)).pack(side="right", padx=2)

        # 사람 체크박스 리스트
        self._recv_sender_checks = {}
        self._recv_senders_data = senders

        for name, dept, cnt in senders:
            f = ctk.CTkFrame(filter_box, fg_color="transparent", height=28)
            f.pack(fill="x", padx=12, pady=0)
            var = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(f, text="", variable=var, width=20, height=20,
                            corner_radius=3, border_width=2,
                            command=self._on_recv_sender_changed).pack(side="left")
            ctk.CTkLabel(f, text=name, font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=C["text"], anchor="w", width=100).pack(side="left", padx=2)
            ctk.CTkLabel(f, text=dept[:20], font=ctk.CTkFont(size=9),
                         text_color=C["text_muted"], anchor="w", width=140).pack(side="left", padx=2)
            ctk.CTkLabel(f, text=f"{cnt}건", font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=C["primary"], fg_color=C["primary_light"],
                         corner_radius=8, width=36, height=16).pack(side="right")
            self._recv_sender_checks[name] = var

        # 초기 건수 표시
        self._update_recv_count()

    def _recv_sender_select_all(self, state):
        for var in self._recv_sender_checks.values():
            var.set(state)
        self._on_recv_sender_changed()

    def _on_recv_sender_changed(self):
        """사람 체크 변경 시 배지 + 건수 + 상단 스탯 즉시 업데이트"""
        self._update_recv_count()
        # 상단 수신 건수도 반영
        if hasattr(self, '_recv_senders_data') and hasattr(self, '_recv_sender_checks'):
            selected = [n for n, v in self._recv_sender_checks.items() if v.get()]
            filtered_recv = sum(cnt for name, dept, cnt in self._recv_senders_data if name in selected)
            prev_text = self.stat_labels["recv"].cget("text")
            new_text = f"{filtered_recv:,}"
            self.stat_labels["recv"].configure(text=new_text)
            # 탭 버튼 건수도 업데이트
            for n, btn in self.tab_btns.items():
                if "받은" in n:
                    btn.configure(text=f"받은 쪽지 {filtered_recv:,}")
            if prev_text != new_text:
                self._flash_stats(["recv"])

    def _update_recv_count(self):
        """선택된 사람에 해당하는 건수를 즉시 계산하여 표시"""
        if not hasattr(self, '_recv_sender_checks'):
            return
        selected = [n for n, v in self._recv_sender_checks.items() if v.get()]
        total = len(self._recv_sender_checks)
        sel_count = len(selected)

        # 배지 업데이트
        if hasattr(self, '_recv_filter_badge'):
            if sel_count == total:
                self._recv_filter_badge.configure(
                    text=f"전체 {total}명 선택",
                    fg_color=C["primary_light"], text_color=C["primary"])
            else:
                self._recv_filter_badge.configure(
                    text=f"{sel_count}/{total}명 선택",
                    fg_color=C["warning_light"], text_color=C["warning"])

        # 선택된 사람의 쪽지 건수 합산
        msg_count = 0
        for name, dept, cnt in self._recv_senders_data:
            if name in selected:
                msg_count += cnt

        if hasattr(self, '_recv_count_label'):
            self._recv_count_label.configure(text=f"→ {msg_count:,}건")

    def _get_selected_senders(self):
        """받은 쪽지 탭에서 선택된 사람 목록 반환"""
        if not hasattr(self, '_recv_sender_checks'):
            return None
        selected = [n for n, v in self._recv_sender_checks.items() if v.get()]
        if len(selected) == len(self._recv_sender_checks):
            return None  # 전체 선택 = 필터 없음
        return selected

    # ── Tab: 보낸 쪽지 ──
    def _tab_sent(self):
        ctk.CTkLabel(self.content_area, text="보낸 쪽지",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]
                     ).pack(anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(self.content_area, text="내가 보낸 쪽지입니다. 필터가 적용됩니다.",
                     font=ctk.CTkFont(size=11), text_color=C["warning"]
                     ).pack(anchor="w", padx=20, pady=(0, 10))
        row = ctk.CTkFrame(self.content_area, fg_color="transparent")
        row.pack(fill="x", padx=20)
        self._dl_card(row, "📤", "발신 CSV 다운로드", "필터 적용된 보낸 쪽지", "orange",
                      lambda: self._export_single("sent"))

    # ── Tab: 대화방 ──
    def _tab_chatrooms(self):
        rooms = self.db.chat_rooms()
        ctk.CTkLabel(self.content_area, text=f"대화방 목록 — {len(rooms)}개",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=C["text"]
                     ).pack(anchor="w", padx=20, pady=(16, 2))

        row = ctk.CTkFrame(self.content_area, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(4, 10))
        self._dl_card(row, "💬", "대화방 CSV", "대화방 목록 내보내기", "purple",
                      lambda: self._export_chatrooms())
        self._dl_card(row, "📝", "대화 메시지 CSV", "전체 대화 내용 내보내기", "green",
                      lambda: self._export_chat_msgs())

        for rm in rooms:
            card = ctk.CTkFrame(self.content_area, fg_color=C["surface"], corner_radius=8,
                                border_width=1, border_color=C["border"])
            card.pack(fill="x", padx=20, pady=3)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)
            name = rm.get("sRoomName") or rm.get("sOriginalRoomName") or "이름없는 대화방"
            ctk.CTkLabel(inner, text=name, font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=C["text"]).pack(anchor="w")
            members = rm.get("sUserNames", "")
            if members:
                ctk.CTkLabel(inner, text=members[:100], font=ctk.CTkFont(size=10),
                             text_color=C["text_sec"], wraplength=600).pack(anchor="w")

    # ── Tab: 미리보기 ──
    # (_tab_preview removed)

    # ── Auto Detect ──
    def _auto_detect(self):
        self._log("자동 감지 중...")
        found = find_talk_db()
        if found:
            best = found[0]
            self._log(f"발견: {best} ({fmt_size(os.path.getsize(best))})")
            self._connect(best)
        else:
            self._log("자동 감지 실패 — '다른 파일' 버튼으로 직접 선택하세요")
            self._switch_tab("쪽지함 전체")

    def _browse_db(self):
        path = filedialog.askopenfilename(
            title="DB 또는 백업 파일 선택",
            filetypes=[("GOE메신저 DB", "*.db"), ("백업 파일", "*.bak"), ("모든 파일", "*.*")]
        )
        if path: self._connect(path)

    def _connect(self, path):
        try:
            if self.db: self.db.close()
            self.db = DBReader(path)
            self._log("복호화 중...")
            self.update()
            self.db.connect(cb=lambda m: self._log(m))
            self._log(f"DB 열기 성공 (테이블 {len(self.db.tables)}개)")

            self.date_min, self.date_max = self.db.date_range()
            if self.date_min:
                self.date_from.delete(0, "end"); self.date_from.insert(0, self.date_min)
                self.date_to.delete(0, "end"); self.date_to.insert(0, self.date_max)

            self._refresh_stats()
            self._populate_depts()
            self._switch_tab("쪽지함 전체")
        except Exception as e:
            self._log(f"오류: {e}")
            messagebox.showerror("오류", str(e))

    def _get_selected_depts(self):
        """선택된 부서 목록 반환 (전체 선택 시 None)"""
        if not self.dept_checks:
            return None
        selected = [d for d, v in self.dept_checks.items() if v.get()]
        if len(selected) == len(self.dept_checks):
            return None  # 전체 선택 = 필터 없음
        return selected

    def _refresh_stats(self):
        if not self.db: return
        df, dt = self._get_dates()
        depts = self._get_selected_depts()

        # 전체 건수 (날짜만)
        s_all = self.db.counts(df, dt)
        # 필터 적용 건수 (날짜 + 부서)
        s = self.db.counts(df, dt, depts)
        self.stats = s
        senders = self.db.senders(df, dt, depts)

        # 이전 값 저장 (변화 감지용)
        prev = {}
        for key in self.stat_labels:
            prev[key] = self.stat_labels[key].cget("text")

        shown = s.get('all', 0)
        total = s_all.get('all', 0)

        # "표시" 는 필터 적용 건수, "전체"는 날짜만 적용 건수
        new_vals = {
            "shown": f"{shown:,}",
            "all": f"{total:,}",
            "sent": f"{s.get('sent', 0):,}",
            "recv": f"{s.get('recv', 0):,}",
            "people": f"{len(senders):,}",
        }

        for key, val in new_vals.items():
            self.stat_labels[key].configure(text=val)

        # 부서 필터 적용 시 "표시" 강조
        if depts is not None:
            self.stat_labels["shown"].configure(text_color=C["warning"])
        else:
            self.stat_labels["shown"].configure(text_color=C["text_sec"])

        self.badge_total.configure(text=f"전체 {total:,}건")

        # Update tab counts (필터 적용된 수치)
        for name, btn in self.tab_btns.items():
            count = ""
            if "전체" in name: count = f" {shown:,}"
            elif "받은" in name: count = f" {s.get('recv', 0):,}"
            elif "보낸" in name: count = f" {s.get('sent', 0):,}"
            elif "대화방" in name: count = f" {s.get('room', 0)}"
            btn.configure(text=f"{name}{count}" if count else name)

        # 값이 변했으면 깜빡임 효과
        changed_keys = [k for k in new_vals if prev.get(k) != new_vals[k]]
        if changed_keys:
            self._flash_stats(changed_keys)

    def _flash_stats(self, keys):
        """변경된 스탯에 노란색 강조 후 원래 색으로 복귀"""
        original_colors = {
            "shown": C["text_sec"], "all": C["text"],
            "sent": C["warning"], "recv": C["primary"], "people": C["accent"]
        }
        # 부서 필터 중이면 shown은 warning 색
        if self._get_selected_depts() is not None:
            original_colors["shown"] = C["warning"]

        for key in keys:
            lbl = self.stat_labels[key]
            lbl.configure(text_color="#dc2626", fg_color="#fef2f2")  # 빨간 강조

        def step2():
            for key in keys:
                lbl = self.stat_labels[key]
                lbl.configure(text_color="#ea580c", fg_color="#fff7ed")  # 주황으로 전환

        def step3():
            for key in keys:
                lbl = self.stat_labels[key]
                lbl.configure(text_color=original_colors.get(key, C["text"]),
                              fg_color="transparent")

        self.after(200, step2)
        self.after(500, step3)

    def _populate_depts(self):
        for w in self.dept_scroll.winfo_children(): w.destroy()
        self.dept_checks.clear()
        df, dt = self._get_dates()
        self.depts = self.db.departments(df, dt)
        self.dept_count_badge.configure(text=str(len(self.depts)))

        # 전체 선택/해제 버튼
        sel_row = ctk.CTkFrame(self.dept_scroll, fg_color="transparent")
        sel_row.pack(fill="x", pady=(0, 4))
        ctk.CTkButton(sel_row, text="전체선택", width=55, height=18,
                      font=ctk.CTkFont(size=9), fg_color="transparent",
                      hover_color=C["primary_light"], text_color=C["primary"],
                      command=lambda: self._dept_select_all(True)).pack(side="left")
        ctk.CTkButton(sel_row, text="전체해제", width=55, height=18,
                      font=ctk.CTkFont(size=9), fg_color="transparent",
                      hover_color=C["danger_light"], text_color=C["danger"],
                      command=lambda: self._dept_select_all(False)).pack(side="left")

        for dept, cnt in self.depts:
            var = ctk.BooleanVar(value=True)
            f = ctk.CTkFrame(self.dept_scroll, fg_color="transparent", height=24)
            f.pack(fill="x", pady=0)
            ctk.CTkCheckBox(f, text="", variable=var, width=20, height=20,
                            corner_radius=3, border_width=2,
                            command=self._on_dept_changed).pack(side="left")
            ctk.CTkLabel(f, text=dept[:28], font=ctk.CTkFont(size=9),
                         text_color=C["text"], anchor="w").pack(side="left", padx=2)
            ctk.CTkLabel(f, text=str(cnt), font=ctk.CTkFont(size=8),
                         text_color=C["text_muted"], fg_color=C["bg"],
                         corner_radius=6, width=28, height=16).pack(side="right")
            self.dept_checks[dept] = var

    def _dept_select_all(self, state):
        for var in self.dept_checks.values():
            var.set(state)
        self._on_dept_changed()

    def _on_dept_changed(self):
        """부서 체크 변경 시 스탯 업데이트 + 현재 탭 새로고침"""
        selected = sum(1 for v in self.dept_checks.values() if v.get())
        total = len(self.dept_checks)
        self.dept_count_badge.configure(text=f"{selected}/{total}")
        # 배지 색상으로 필터 상태 표시
        if selected == total:
            self.dept_count_badge.configure(fg_color=C["primary_light"],
                                            text_color=C["primary"])
        elif selected == 0:
            self.dept_count_badge.configure(fg_color=C["danger_light"],
                                            text_color=C["danger"])
        else:
            self.dept_count_badge.configure(fg_color=C["warning_light"],
                                            text_color=C["warning"])
        # 스탯과 탭 갱신
        self._refresh_stats()
        self._switch_tab(self.current_tab.get())

    # ── Export Functions ──
    def _run_export(self, func):
        if self.processing: return
        self.processing = True
        self._log("내보내기 시작...")
        threading.Thread(target=self._safe_export, args=(func,), daemon=True).start()

    def _safe_export(self, func):
        try:
            func()
        except Exception as e:
            self.after(0, lambda: self._log(f"오류: {e}"))
        finally:
            self.after(0, self._export_done)

    def _export_done(self):
        self.processing = False

    def _export_all_zip(self):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            # All notes
            rows = self.db.notes(df, dt)
            write_csv(os.path.join(d, f"쪽지함_전체_{len(rows)}건.csv"), rows, NOTE_FIELDS)
            # Recv
            recv = self.db.notes(df, dt, "recv")
            write_csv(os.path.join(d, f"받은쪽지_{len(recv)}건.csv"), recv, NOTE_FIELDS)
            # Sent
            sent = self.db.notes(df, dt, "sent")
            write_csv(os.path.join(d, f"보낸쪽지_{len(sent)}건.csv"), sent, NOTE_FIELDS)
            # By sender
            by = defaultdict(list)
            for r in recv: by[r["보낸사람"]].append(r)
            pd = os.path.join(d, "수신_사람별"); os.makedirs(pd, exist_ok=True)
            for name, pr in sorted(by.items(), key=lambda x: -len(x[1])):
                safe = re.sub(r'[\\/:*?"<>|]', '_', name).strip() or "이름없음"
                dept = pr[0].get("소속", "")
                write_csv(os.path.join(pd, f"{safe} {dept}_{len(pr)}건.csv"), pr, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"전체 ZIP 완료: {d}"))
            os.startfile(d)
        self._run_export(do)

    def _export_single(self, direction):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            rows = self.db.notes(df, dt, direction)
            # 받은 쪽지 탭에서 사람 필터 적용
            if direction == "recv":
                sel = self._get_selected_senders()
                if sel is not None:
                    rows = [r for r in rows if r["보낸사람"] in sel]
            labels = {"all": "쪽지함_전체", "recv": "받은쪽지", "sent": "보낸쪽지"}
            fp = os.path.join(d, f"{labels[direction]}_{len(rows)}건.csv")
            write_csv(fp, rows, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"{labels[direction]} {len(rows)}건 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_filtered(self):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            rows = self.db.notes(df, dt)
            # Apply keyword filter
            fp = os.path.join(d, f"필터적용_{len(rows)}건.csv")
            write_csv(fp, rows, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"필터 적용 {len(rows)}건 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_by_dept(self):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            rows = self.db.notes(df, dt)
            by = defaultdict(list)
            for r in rows: by[r["소속"] or "소속미상"].append(r)
            dd = os.path.join(d, "부서별"); os.makedirs(dd, exist_ok=True)
            for dept, dr in sorted(by.items()):
                safe = re.sub(r'[\\/:*?"<>|]', '_', dept).strip()
                write_csv(os.path.join(dd, f"{safe}_{len(dr)}건.csv"), dr, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"부서별 {len(by)}개 부서 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_by_month(self):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            rows = self.db.notes(df, dt)
            by = defaultdict(list)
            for r in rows: by[r["날짜"][:7] if r["날짜"] else "기타"].append(r)
            md = os.path.join(d, "월별"); os.makedirs(md, exist_ok=True)
            for ym, mr in sorted(by.items()):
                write_csv(os.path.join(md, f"{ym}_{len(mr)}건.csv"), mr, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"월별 {len(by)}개월 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_by_year(self):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            rows = self.db.notes(df, dt)
            by = defaultdict(list)
            for r in rows: by[r["날짜"][:4] if r["날짜"] else "기타"].append(r)
            yd = os.path.join(d, "연도별"); os.makedirs(yd, exist_ok=True)
            for yr, yr_rows in sorted(by.items()):
                write_csv(os.path.join(yd, f"{yr}_{len(yr_rows)}건.csv"), yr_rows, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"연도별 {len(by)}년 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_by_person(self):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            recv = self.db.notes(df, dt, "recv")
            # 선택된 사람 필터 적용
            sel = self._get_selected_senders()
            if sel is not None:
                recv = [r for r in recv if r["보낸사람"] in sel]
            by = defaultdict(list)
            for r in recv: by[r["보낸사람"]].append(r)
            pd = os.path.join(d, "수신_사람별"); os.makedirs(pd, exist_ok=True)
            for name, pr in sorted(by.items(), key=lambda x: -len(x[1])):
                safe = re.sub(r'[\\/:*?"<>|]', '_', name).strip() or "이름없음"
                dept = pr[0].get("소속", "")
                write_csv(os.path.join(pd, f"{safe} {dept}_{len(pr)}건.csv"), pr, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"사람별 {len(by)}명 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_by_receiver(self):
        def do():
            df, dt = self._get_dates()
            d = self._export_path()
            sent = self.db.notes(df, dt, "sent")
            by = defaultdict(list)
            for r in sent:
                if r["수신자"]:
                    for nm in r["수신자"].split(","):
                        nm = nm.strip()
                        if nm: by[nm].append(r)
            rd = os.path.join(d, "발신_수신자별"); os.makedirs(rd, exist_ok=True)
            for name, pr in sorted(by.items(), key=lambda x: -len(x[1])):
                safe = re.sub(r'[\\/:*?"<>|]', '_', name).strip() or "이름없음"
                write_csv(os.path.join(rd, f"{safe}_{len(pr)}건.csv"), pr, NOTE_FIELDS)
            self.after(0, lambda: self._log(f"수신자별 {len(by)}명 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_chatrooms(self):
        def do():
            d = self._export_path()
            rooms = self.db.chat_rooms()
            write_csv(os.path.join(d, f"대화방목록_{len(rooms)}개.csv"), rooms)
            self.after(0, lambda: self._log(f"대화방 {len(rooms)}개 저장 완료"))
            os.startfile(d)
        self._run_export(do)

    def _export_chat_msgs(self):
        def do():
            d = self._export_path()
            msgs = self.db.chat_msgs()
            write_csv(os.path.join(d, f"대화메시지_{len(msgs)}건.csv"), msgs)
            self.after(0, lambda: self._log(f"대화 메시지 {len(msgs)}건 저장 완료"))
            os.startfile(d)
        self._run_export(do)


if __name__ == "__main__":
    App().mainloop()
