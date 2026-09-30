# PyInstaller build file. Run `pyinstaller CollisionTest.spec` to get
# dist/CollisionTest.exe on Windows or dist/CollisionTest.app on macOS.
# PyInstaller can't cross-compile, so each one has to be built on its own OS
# (.github/workflows/build.yml does both on GitHub).
import sys

from PyInstaller.utils.hooks import collect_all

datas = [("pic/image.png", "pic")]
binaries = []
hiddenimports = []
# raylib ships a compiled library that PyInstaller doesn't find by itself.
for package in ("raylib", "pyray"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(["main.py"], datas=datas, binaries=binaries, hiddenimports=hiddenimports)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # A normal double-clickable Mac app.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="CollisionTest", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="CollisionTest")
    app = BUNDLE(
        coll,
        name="CollisionTest.app",
        bundle_identifier="com.suhrab.collisiontest",
        info_plist={
            # Shown when macOS asks the player to allow local network access, which the game
            # needs to find the host.
            "NSLocalNetworkUsageDescription": "Collision Test looks for the game's host on your local network.",
        },
    )
else:
    # One self-contained .exe with no console window.
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="CollisionTest", console=False)
