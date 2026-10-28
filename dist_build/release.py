"""새 버전 배포(개발 PC 전용). GitHub CLI(gh) 로그인 필요.
python release.py <버전> "변경 1" "변경 2" ... [--notes-file=notes.txt] [--runtime] [--full] [--dry]
  (PowerShell 에서 한글 인자가 깨지면 --notes-file 로. Bash 도구에서는 인자 직접 가능)
  --runtime : pkg/runtime 도 zip 으로 묶어 runtime-v<N> 릴리스(런타임 바뀐 때만)
  --full    : 처음 나눠줄 전체 패키지 zip(bat+app+runtime+사용법)도 만들어 릴리스에 첨부
  --shell   : 데스크탑 앱(Electron) 설치본 GirderTool-Setup-<버전>.exe 도 빌드·첨부(desktop/ 코드가 바뀐 때만, ~170MB)
  --dry     : 파일만 만들고 gh/git 은 실행하지 않음
동작: 소스 → pkg/app 복사·version.txt → app.zip → gh release(app-v<버전>) → latest.json·CHANGELOG 갱신 → git commit/push
"""
import os, sys, json, shutil, zipfile, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                     # DwgRework (소스·git 저장소)
PKG = os.path.join(HERE, "pkg"); APP = os.path.join(PKG, "app"); RT = os.path.join(PKG, "runtime")
OUT = os.path.join(HERE, "out"); TPL = os.path.join(HERE, "template")
APP_FILES = ["cfg.py", "dxfio.py", "geom.py", "dump.py", "stage1_select.py", "stage2_model.py", "stage2_engine.py",
             "stage2_gen.py", "final_write.py", "render_html.py", "run_pipeline.py", "updater.py", "feedback.py", "xref_bind.py", "stage3_mgt.py"]
GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def sh(cmd, **kw):
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=True, text=True, encoding="utf-8", capture_output=True, **kw).stdout


def zipdir(src, dst, prefix=""):
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for r, ds, fs in os.walk(src):
            ds[:] = [d for d in ds if d != "__pycache__"]
            for f in fs:
                p = os.path.join(r, f); z.write(p, prefix + os.path.relpath(p, src))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        sys.exit(__doc__)
    ver, notes = args[0].lstrip("v"), args[1:]
    nf = [a for a in flags if a.startswith("--notes-file=")]  # PowerShell 은 한글 인자가 깨지므로 파일(UTF-8, 한 줄=항목)로도 받음
    if nf:
        notes += [l.strip("- ").strip() for l in open(nf[0].split("=", 1)[1], encoding="utf-8-sig").read().splitlines() if l.strip()]
        flags -= set(nf)
    if not notes:
        sys.exit("변경 내용(notes)이 없음: 인자 또는 --notes-file=파일 로 지정")
    dry = "--dry" in flags
    try:
        repo = sh([GH, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()
    except Exception as e:
        if not dry:
            raise
        repo = "Torix0615/dwg-girder-tool"; print(f"(dry) gh 미사용: {e}")
    latest_p = os.path.join(SRC, "latest.json")
    latest = json.load(open(latest_p, encoding="utf-8")) if os.path.exists(latest_p) else {"notes": []}
    # 1. app 폴더 구성
    if os.path.exists(APP):
        shutil.rmtree(APP)
    os.makedirs(APP); os.makedirs(OUT, exist_ok=True)
    for f in APP_FILES:
        shutil.copy2(os.path.join(SRC, f), os.path.join(APP, f))
    shutil.copy2(os.path.join(SRC, "config.json"), os.path.join(APP, "config.default.json"))
    open(os.path.join(APP, "version.txt"), "w", encoding="utf-8").write(ver)
    open(os.path.join(APP, "update_source.txt"), "w", encoding="utf-8").write(f"https://raw.githubusercontent.com/{repo}/main/latest.json")
    sec_p = os.path.join(HERE, "secrets.json")  # 피드백 서버 주소(git 제외) → app/feedback_server.txt. 키는 pull_feedback 전용이라 앱에 넣지 않음
    if os.path.exists(sec_p):
        sec = json.load(open(sec_p, encoding="utf-8"))
        if sec.get("feedback_url"):
            open(os.path.join(APP, "feedback_server.txt"), "w", encoding="utf-8").write(sec["feedback_url"].strip() + "\n")
    else:
        print("경고: dist_build/secrets.json 없음 → 앱에서 피드백 전송 대신 파일 저장만 됨")
    # 2. 패키지 루트(bat·사용법·config)
    for f in os.listdir(TPL):
        shutil.copy2(os.path.join(TPL, f), os.path.join(PKG, f))
    shutil.copy2(os.path.join(SRC, "config.json"), os.path.join(PKG, "config.json"))
    # 3. app.zip
    app_zip = os.path.join(OUT, "app.zip"); zipdir(APP, app_zip)
    print(f"app.zip {os.path.getsize(app_zip)/1e3:.0f} KB")
    # 4. latest.json / CHANGELOG
    date = time.strftime("%Y-%m-%d")
    latest["app_version"] = ver
    latest["app_url"] = f"https://github.com/{repo}/releases/download/app-v{ver}/app.zip"
    latest["notes"] = [{"version": ver, "date": date, "items": notes}] + [n for n in latest.get("notes", []) if n.get("version") != ver]
    latest["notes"] = latest["notes"][:20]
    rt_ver = open(os.path.join(RT, "runtime_version.txt"), encoding="utf-8").read().strip()
    if "--runtime" in flags:
        rt_zip = os.path.join(OUT, "runtime.zip"); zipdir(RT, rt_zip)
        print(f"runtime.zip {os.path.getsize(rt_zip)/1e6:.0f} MB")
        latest["runtime_version"] = rt_ver
        latest["runtime_url"] = f"https://github.com/{repo}/releases/download/runtime-v{rt_ver}/runtime.zip"
        if not dry:
            sh([GH, "release", "create", f"runtime-v{rt_ver}", rt_zip, "--title", f"runtime {rt_ver}", "--notes", "Python 3.14 embedded + ezdxf/shapely/scipy/numpy/matplotlib + dwg2dxf"])
    latest.setdefault("runtime_version", rt_ver)
    # 4b. 데스크탑 셸(Electron 설치본): --shell 일 때만 빌드(엔진·런타임 포함 ~170MB). 설치된 앱은 창을 숨길 때 무인 설치
    shell_exe = None
    if "--shell" in flags:
        desk = os.path.join(SRC, "desktop"); pj = os.path.join(desk, "package.json")
        pkg = json.load(open(pj, encoding="utf-8")); pkg["version"] = ver
        json.dump(pkg, open(pj, "w", encoding="utf-8"), ensure_ascii=False, indent=2); open(pj, "a", encoding="utf-8").write("\n")
        print("electron-builder 빌드 중(수 분)…")
        r = subprocess.run(["npm.cmd", "run", "dist"], cwd=desk, text=True, encoding="utf-8", errors="replace", capture_output=True)
        print(r.stdout[-1500:])
        if r.returncode != 0:
            sys.exit("electron-builder 실패:\n" + r.stderr[-3000:])
        shell_exe = os.path.join(desk, "release", f"GirderTool-Setup-{ver}.exe")
        if not os.path.exists(shell_exe):
            sys.exit(f"설치본이 없음: {shell_exe}")
        import hashlib
        sha = hashlib.sha256(open(shell_exe, "rb").read()).hexdigest()
        latest["shell_version"] = ver
        latest["shell_url"] = f"https://github.com/{repo}/releases/download/app-v{ver}/GirderTool-Setup-{ver}.exe"
        latest["shell_sha256"] = sha
        latest["shell_size"] = os.path.getsize(shell_exe)
        print(f"설치본 {os.path.getsize(shell_exe)/1e6:.0f} MB sha256={sha[:12]}…")
    json.dump(latest, open(latest_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ch = os.path.join(SRC, "CHANGELOG.md")
    old = open(ch, encoding="utf-8").read() if os.path.exists(ch) else "# 변경 이력\n"
    entry = f"\n## v{ver} ({date})\n" + "".join(f"- {n}\n" for n in notes)
    open(ch, "w", encoding="utf-8").write(old.rstrip("\n") + "\n" + entry)
    # 5. 전체 패키지 zip
    assets = [app_zip]
    if "--full" in flags:
        full = os.path.join(OUT, f"girder-tool_v{ver}_full.zip")  # GitHub 자산명은 한글이 지워지므로 영문
        zipdir(PKG, full, prefix="골조거더보/")
        print(f"전체 패키지 {os.path.getsize(full)/1e6:.0f} MB → {full}")
        assets.append(full)
    if shell_exe:
        assets.append(shell_exe)
        readme = os.path.join(HERE, "README.txt")  # 설치본과 함께 전달하는 사용자 안내문
        if os.path.exists(readme):
            assets.append(readme)
    if dry:
        print("(dry) gh/git 생략"); return
    # 6. 릴리스 + 저장소 반영
    sh([GH, "release", "create", f"app-v{ver}", *assets, "--title", f"v{ver}", "--notes", "\n".join(f"- {n}" for n in notes) or f"v{ver}"])
    subprocess.run(["git", "add", "-A"], cwd=SRC, check=True)
    subprocess.run(["git", "commit", "-m", f"release v{ver}\n\n" + "\n".join(f"- {n}" for n in notes)], cwd=SRC, check=True)
    subprocess.run(["git", "push"], cwd=SRC, check=True)
    print(f"\n배포 완료 v{ver}: 상대 PC 는 다음 실행 때 자동 업데이트됨")


if __name__ == "__main__":
    main()
