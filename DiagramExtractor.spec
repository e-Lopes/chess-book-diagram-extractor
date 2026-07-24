# -*- mode: python ; coding: utf-8 -*-
"""Configuracao reproduzivel do executavel Windows."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


raiz = Path(SPECPATH)
gerados = raiz / "build" / "generated"
dados_cv2, binarios_cv2, imports_cv2 = collect_all("cv2")
dados = dados_cv2 + [(str(raiz / "icon" / "icon.png"), "icon")]

a = Analysis(
    [str(raiz / "interface_windows.py")],
    pathex=[str(raiz), str(gerados)],
    binaries=binarios_cv2,
    datas=dados,
    hiddenimports=imports_cv2,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ChessBookDiagramExtractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=str(gerados / "version_info.txt"),
    icon=str(raiz / "icon" / "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ChessBookDiagramExtractor",
)
