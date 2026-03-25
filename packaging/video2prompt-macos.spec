# -*- mode: python ; coding: utf-8 -*-

import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


SPEC_DIR = os.path.abspath(globals().get("SPECPATH", os.getcwd()))
ROOT_DIR = os.path.dirname(SPEC_DIR)


streamlit_hiddenimports = collect_submodules("streamlit")
app_hiddenimports = collect_submodules("video2prompt")
streamlit_datas = collect_data_files("streamlit")
streamlit_metadata = copy_metadata("streamlit")

datas = [
    (os.path.join(ROOT_DIR, "app.py"), "."),
    (os.path.join(ROOT_DIR, "config.yaml"), "."),
    (os.path.join(ROOT_DIR, ".env.example"), "."),
    (os.path.join(ROOT_DIR, "docs"), "docs"),
]
datas += streamlit_datas
datas += streamlit_metadata

binaries = [
    (os.path.join(ROOT_DIR, "packaging", "bin", "ffprobe"), "bin"),
]
for library_path in glob.glob(os.path.join(ROOT_DIR, "packaging", "bin", "lib", "*.dylib")):
    binaries.append((library_path, "bin/lib"))

a = Analysis(
    [os.path.join(ROOT_DIR, "src", "video2prompt", "desktop_entry.py")],
    pathex=[os.path.join(ROOT_DIR, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=streamlit_hiddenimports
    + app_hiddenimports
    + ["app", "streamlit.web.bootstrap", "streamlit.web.cli"],
    hookspath=[],
    hooksconfig={},
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
    name="video2prompt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="video2prompt",
)

app = BUNDLE(
    coll,
    name="视频分析.app",
    icon=os.path.join(ROOT_DIR, "icon.icns"),
    bundle_identifier="com.video2prompt.app",
    info_plist={
        "CFBundleDisplayName": "视频分析",
        "CFBundleName": "视频分析",
        "LSUIElement": True,
    },
)
