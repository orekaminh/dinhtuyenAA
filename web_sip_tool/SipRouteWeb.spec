# -*- mode: python ; coding: utf-8 -*-
import time
import os

# Tránh lỗi Permission denied do Windows Defender/Antivirus tạm khóa file .exe vừa tạo để quét
try:
    import PyInstaller.utils.win32.winutils as winutils

    _orig_set_exe_build_timestamp = getattr(winutils, 'set_exe_build_timestamp', None)
    if _orig_set_exe_build_timestamp:
        def _safe_set_exe_build_timestamp(exe_path, build_timestamp):
            for _ in range(20):
                try:
                    return _orig_set_exe_build_timestamp(exe_path, build_timestamp)
                except Exception:
                    time.sleep(1.5)
            pass
        winutils.set_exe_build_timestamp = _safe_set_exe_build_timestamp

    _orig_update_exe_pe_checksum = getattr(winutils, 'update_exe_pe_checksum', None)
    if _orig_update_exe_pe_checksum:
        def _safe_update_exe_pe_checksum(exe_path):
            for _ in range(20):
                try:
                    return _orig_update_exe_pe_checksum(exe_path)
                except Exception:
                    time.sleep(1.5)
            pass
        winutils.update_exe_pe_checksum = _safe_update_exe_pe_checksum
except Exception:
    pass


a = Analysis(
    ['SNOC2_RouteAA.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static')],
    hiddenimports=['engineio.async_drivers.threading'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SNOC2_RouteAA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
