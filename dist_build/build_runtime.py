"""배포용 런타임 묶기: 임베디드 Python + 필요한 패키지 + dwg2dxf → pkg/runtime
python build_runtime.py   (dist_build 폴더에서)
"""
import os, shutil, zipfile, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "pkg")
RT = os.path.join(PKG, "runtime")
SITE = os.path.join(os.environ["APPDATA"], "Python", "Python314", "site-packages")
LIBREDWG = os.path.join(os.path.dirname(os.path.dirname(HERE)), "libredwg")
RUNTIME_VERSION = "1"
PKGS = ["ezdxf", "shapely", "shapely.libs", "scipy", "scipy.libs", "numpy", "numpy.libs",
        "matplotlib", "mpl_toolkits", "PIL", "fontTools", "kiwisolver", "cycler", "pyparsing",
        "dateutil", "contourpy", "packaging"]
FILES = ["six.py", "typing_extensions.py", "pylab.py"]
SKIP_DIRS = {"__pycache__", "tests", "test"}


def copytree(src, dst):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, src)
        out = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out, exist_ok=True)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            shutil.copy2(os.path.join(root, f), os.path.join(out, f))


if os.path.exists(RT):
    shutil.rmtree(RT)
os.makedirs(RT)
with zipfile.ZipFile(os.path.join(HERE, "dl", "python-embed.zip")) as z:
    z.extractall(RT)
pth = [f for f in os.listdir(RT) if f.endswith("._pth")][0]
open(os.path.join(RT, pth), "w").write("python314.zip\n.\nLib\\site-packages\n..\\app\n")  # ._pth 가 있으면 스크립트 폴더가 sys.path 에 안 들어감 → app 명시
sp = os.path.join(RT, "Lib", "site-packages")
os.makedirs(sp)
for p in PKGS:
    src = os.path.join(SITE, p)
    if not os.path.isdir(src):
        sys.exit(f"패키지 없음: {src}")
    copytree(src, os.path.join(sp, p))
    print("copied", p)
for f in FILES:
    shutil.copy2(os.path.join(SITE, f), os.path.join(sp, f))
for f in os.listdir(LIBREDWG):
    if f == "dwg2dxf.exe" or f.lower().endswith(".dll"):
        shutil.copy2(os.path.join(LIBREDWG, f), os.path.join(RT, f))
open(os.path.join(RT, "runtime_version.txt"), "w").write(RUNTIME_VERSION)
total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(RT) for f in fs)
print(f"runtime 완료: {total/1e6:.0f} MB → {RT}")
