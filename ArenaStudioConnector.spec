# PyInstaller-Spec: baut EINE einzelne ArenaStudioConnector.exe
# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ["arena_studio_connector.py"],
    pathex=[],
    binaries=[],
    datas=[("plugin/ArenaBridgePlugin.lua", "plugin")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="ArenaStudioConnector",
    debug=False, bootloader_ignore_signals=False, strip=False,
    upx=True, console=False,  # kein Konsolenfenster, nur die GUI
)
