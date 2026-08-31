# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("customtkinter", "pykrx"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
datas += [("data", "data")]

a = Analysis(["app.py"], pathex=[], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="peer_wacc", debug=False, strip=False, upx=True,
          console=False, disable_windowed_traceback=False)
