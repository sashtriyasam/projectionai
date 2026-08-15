# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ProjectionAI desktop application.

Build with:  uv run pyinstaller --noconfirm packaging/projectionai.spec
Output:      dist/ProjectionAI/ProjectionAI.exe  (onedir, windowed)
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = collect_all("PySide6")

shader_datas = collect_data_files(
    "projectionai",
    includes=["infrastructure/renderer/shaders/*"],
)

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas + shader_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ProjectionAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="../build/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ProjectionAI",
)