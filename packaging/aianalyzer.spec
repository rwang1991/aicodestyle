# PyInstaller spec for the AIAnalyzer standalone .exe.
#
# Build with:  pyinstaller packaging/aianalyzer.spec --clean --noconfirm
# Output:      dist/aianalyzer.exe  (single-file Windows executable)
#
# Why this is a spec file (not a one-line CLI command):
# - The two data bundles (weights.yaml and the entire web/static/ tree) are
#   load-bearing; missing them means the .exe boots but the portal returns
#   404s. A spec captures them as version-controlled config.
# - uvicorn discovers ASGI middleware via importlib at runtime, which
#   PyInstaller's static analyzer cannot see. ``collect_submodules('uvicorn')``
#   pulls them in.
# - We always want --onefile + console build (B1: console + browser). The spec
#   pins these so anyone running the build script gets the same result.

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).resolve().parent     # repo root (spec lives in packaging/)
SRC = ROOT / "src"

# Data files. PyInstaller wants tuples of (source_path_str, dest_dir_in_bundle).
# ``__file__``-based code in aianalyzer/web/app.py resolves STATIC_DIR via
# ``Path(__file__).parent / "static"`` so the dest dir must mirror the package
# layout exactly: aianalyzer/web/static, aianalyzer/classifier.
datas = [
    (str(SRC / "aianalyzer" / "classifier" / "weights.yaml"),
     "aianalyzer/classifier"),
]
# Bundle every file under web/static (HTML, JS, CSS, vendored Chart.js,
# marked.min.js). ``collect_data_files`` recurses and preserves structure.
datas += collect_data_files(
    "aianalyzer.web",
    includes=["static/**/*"],
)
# tiktoken (Phase F): the BPE merge tables live as package data. Without
# this PyInstaller bundles the .py but loads fail at runtime because the
# tiktoken_ext registry can't find the .tiktoken merge files.
datas += collect_data_files("tiktoken")
datas += collect_data_files("tiktoken_ext")
# Pre-warmed BPE cache so the .exe never tries to download cl100k_base
# from openaipublic on first run (kills offline use + corporate proxy issues).
datas += [(str(ROOT / "packaging" / "tiktoken_cache" / "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"),
           "tiktoken_cache")]

# Hidden imports. uvicorn lazy-loads protocol/lifespan plugins; FastAPI does
# the same for some response classes. Static analysis misses them.
hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
# tiktoken loads its encoders via a runtime plugin registry; PyInstaller's
# static analyzer can't see the dotted-string imports. Without this the
# .exe raises "Unknown encoding cl100k_base" the first time anyone scans.
hiddenimports += collect_submodules("tiktoken_ext")
hiddenimports += [
    # uvicorn[standard] extras that are imported by string name at runtime.
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # duckdb's C-extension module name (the python package is "duckdb").
    "duckdb.duckdb",
]


a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "rthook_tiktoken.py")],
    excludes=[
        # Trim weight: test frameworks should never end up in the shipped .exe.
        "pytest",
        "_pytest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

# We build in --onedir mode (EXE + COLLECT) instead of --onefile because
# corporate Windows Defender Application Control / AppLocker policies often
# block PyInstaller's "extract embedded python.dll to %TEMP% and load it"
# behaviour. With --onedir, python312.dll sits next to the .exe in a
# trusted folder and is loaded directly — no temp extraction, no AV alarm.
# Cost: teammates receive a zipped folder (~80 MB) instead of a single
# 49 MB exe.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="aianalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX often triggers AV false positives; not worth it.
    console=True,          # Variant B1: keep the console window visible.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="aianalyzer",
)
