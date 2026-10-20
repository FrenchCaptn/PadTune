# -*- mode: python ; coding: utf-8 -*-
# Construction de PadTune.exe :  pyinstaller padtune.spec   (sous Windows)
import sys
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("bleak")
if sys.platform == "win32":
    # bleak charge son moteur Windows (WinRT) dynamiquement : on inclut les modules nécessaires
    hidden += collect_submodules("winrt")

a = Analysis(
    ["padtune.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/padtune.ico", "assets"), ("assets/padtune_256.png", "assets")],
    hiddenimports=hidden + ["translations"],
    excludes=["tkinter", "pytest", "numpy", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PadTune",
    icon="assets/padtune.ico",
    version="version_info.txt" if sys.platform == "win32" else None,
    console=False,          # pas de fenêtre noire
    upx=False,              # UPX augmente les faux positifs antivirus
    debug=False,
    strip=False,
)
