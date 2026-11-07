# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
ffmpeg_dir = Path(os.environ.get('FFMPEG_DIR', ''))
if not all((ffmpeg_dir / name).is_file() for name in ('ffmpeg.exe', 'ffprobe.exe')):
    raise SystemExit('Set FFMPEG_DIR to the directory containing ffmpeg.exe and ffprobe.exe')


a = Analysis(
    ['packaged_entry.py'],
    pathex=[],
    binaries=[(str(ffmpeg_dir / 'ffmpeg.exe'), 'ffmpeg'), (str(ffmpeg_dir / 'ffprobe.exe'), 'ffmpeg')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'pandas', 'IPython', 'pytest'],
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
    name='FishTracker',
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
