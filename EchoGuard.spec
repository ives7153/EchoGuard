# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the EchoGuard PyQt upper computer."""

from pathlib import Path


project_root = Path(SPECPATH)
assets_dir = project_root / "upper_computer" / "assets"
icon_path = assets_dir / "app_icon.ico"

datas = [
    (str(assets_dir / "app_icon.ico"), "upper_computer/assets"),
    (str(assets_dir / "app_icon.png"), "upper_computer/assets"),
]

excluded_modules = [
    "dearpygui",
    "OpenGL",
    "pyqtgraph.opengl",
    "pyqtgraph.multiprocess",
    "psutil",
    "scipy",
    "upper_computer.utils.export",
    "upper_computer.viz.dashboard",
]

a = Analysis(
    ["scripts/echoguard_pyinstaller_entry.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["PyQt6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EchoGuard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EchoGuard",
)
