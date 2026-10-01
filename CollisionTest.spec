# PyInstaller build file. Run `pyinstaller CollisionTest.spec` to get
# dist/CollisionTest.exe on Windows or dist/CollisionTest.app on macOS.
# PyInstaller can't cross-compile, so each one has to be built on its own OS
# (.github/workflows/build.yml does both on GitHub).
import os
import subprocess
import sys

from PyInstaller.utils.hooks import collect_all


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=SPECPATH).stdout.strip()


# The version the game shows. GitHub builds use the same number as their release ("Build 3");
# builds made on your own computer say so, and whether they include uncommitted changes.
commit = git("rev-parse", "--short", "HEAD")
if os.environ.get("GITHUB_RUN_NUMBER"):
    version = f"Build {os.environ['GITHUB_RUN_NUMBER']} ({commit})"
else:
    version = f"Local build ({commit}{', with changes' if git('status', '--porcelain') else ''})"
version_file = os.path.join(SPECPATH, "build", "version.txt")
os.makedirs(os.path.dirname(version_file), exist_ok=True)
with open(version_file, "w") as f:
    f.write(version)

datas = [("pic/image.png", "pic"), (version_file, ".")]
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
