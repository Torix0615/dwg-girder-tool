"""원본 DWG/DXF 1개 → 1단계(골조 추출) → 2단계(거더·보) → 편집 가능한 완성 DXF.
python run_pipeline.py <원본.dwg|.dxf> [--out 폴더] [--config config.json] [--html] [--keep]
결과: <원본이름>_골조거더보.dxf (+ _report.txt, --html 이면 층별 도면 HTML 2개) — 기본은 원본 파일 옆.
중간 파일은 work/<원본이름>/ (--keep 없으면 완료 후 삭제).
"""
import sys, os, subprocess, time, shutil, argparse, traceback, platform

HERE = os.path.dirname(os.path.abspath(__file__))
# 배포 패키지(<루트>\app\run_pipeline.py + <루트>\runtime\python.exe)면 루트 기준, 아니면 개발 폴더 기준
ROOT = os.path.dirname(HERE) if os.path.basename(HERE).lower() == "app" else HERE
_cands = [os.path.join(os.path.dirname(sys.executable), "dwg2dxf.exe"), os.path.join(ROOT, "runtime", "dwg2dxf.exe"),
          os.path.join(os.path.dirname(HERE), "libredwg", "dwg2dxf.exe")]
DWG2DXF = next((p for p in _cands if os.path.exists(p)), _cands[-1])
ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("--out"); ap.add_argument("--config"); ap.add_argument("--html", action="store_true"); ap.add_argument("--keep", action="store_true")
a = ap.parse_args()
src = os.path.abspath(a.src)
base = os.path.splitext(os.path.basename(src))[0]
outdir = os.path.abspath(a.out) if a.out else os.path.dirname(src)
work = os.path.join(ROOT, "work", f"{base}_{os.getpid()}")  # 같은 파일을 동시에 돌려도 충돌 없게 실행별 폴더
cfg_path = os.path.abspath(a.config) if a.config else (os.path.join(ROOT, "config.json") if ROOT != HERE else None)
cfg_args = ["--config", cfg_path] if cfg_path and os.path.exists(cfg_path) else []
env = dict(os.environ, PYTHONUTF8="1")
_ver = os.path.join(HERE, "version.txt")
APP_VER = open(_ver, encoding="utf-8").read().strip() if os.path.exists(_ver) else "dev"
log = [f"입력: {src}\n출력 폴더: {outdir}\n버전: {APP_VER}\n설정: {cfg_path or '(기본값)'}\npython: {sys.executable} ({platform.python_version()})\n시작: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
T0 = time.time()
REPORT = os.path.join(outdir, f"{base}_골조거더보_report.txt")
LOGCOPY = os.path.join(ROOT, "logs", time.strftime("%Y%m%d_%H%M%S") + f"_{base}_report.txt")  # 피드백 zip 에 넣을 사본


def save_report():
    txt = "\n\n".join(log)
    for p in (REPORT, LOGCOPY):
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8-sig").write(txt)
        except OSError as e:
            print(f"report 저장 실패: {e}", flush=True)


def step(name, cmd):
    t = time.time()
    print(f"\n=== {name}", flush=True)
    r = subprocess.run(cmd, cwd=HERE, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    tail = (r.stdout or "").strip().splitlines()[-6:]
    print("\n".join(tail), flush=True)
    log.append(f"[{name}] {time.time()-t:.0f}s\n" + "\n".join(tail))
    save_report()
    if r.returncode != 0:
        print(r.stderr[-3000:], flush=True)
        log.append("[오류 출력]\n" + r.stderr[-3000:])
        raise SystemExit(f"{name} 실패 (코드 {r.returncode})")


def main():
    print(f"골조·거더·보 생성 v{APP_VER} | 입력: {os.path.basename(src)}", flush=True)
    if not os.path.exists(src):
        raise SystemExit(f"입력 파일 없음: {src}")
    os.makedirs(work, exist_ok=True); os.makedirs(outdir, exist_ok=True)
    save_report()
    # 0. DWG → DXF
    dxf = src
    if src.lower().endswith(".dwg"):
        if not os.path.exists(DWG2DXF):
            raise SystemExit(f"dwg2dxf.exe 없음: {DWG2DXF}")
        dxf = os.path.join(work, base + ".dxf")
        if not os.path.exists(dxf):
            step("DWG→DXF 변환(LibreDWG)", [DWG2DXF, "-y", "-o", dxf, src])
        if not os.path.exists(dxf):
            raise SystemExit("dwg2dxf 변환 실패(DXF 가 만들어지지 않음)")
    elif not src.lower().endswith(".dxf"):
        raise SystemExit("입력은 .dwg 또는 .dxf 여야 함")
    py = [sys.executable]
    d1, cand, model, res, final = (os.path.join(work, f) for f in ("d1.pkl", "s1_cand.pkl", "s2_model.pkl", "s2_result.pkl", "최종.dxf"))
    step("원본 전개(블록 재귀)", py + ["dump.py", dxf, d1, "--msp"])
    step("1단계 골조·중심선·OPEN 선별", py + ["stage1_select.py", d1, cand] + cfg_args)
    step("2단계 구조 모델(기둥·벽·동)", py + ["stage2_model.py", cand, model] + cfg_args)
    step("2단계 거더·보 생성", py + ["stage2_gen.py", model, res, "--report", os.path.join(work, "gen_report.txt")] + cfg_args)
    step("최종 DXF 작성", py + ["final_write.py", cand, model, res, final] + cfg_args)
    dst = os.path.join(outdir, f"{base}_골조거더보.dxf")
    shutil.copyfile(final, dst)
    if a.html:
        hdir = os.path.join(work, "html")
        step("층별 도면 HTML", py + ["render_html.py", final, hdir])
        for f in os.listdir(hdir):
            if f.endswith(".html"):
                shutil.copyfile(os.path.join(hdir, f), os.path.join(outdir, f"{base}_{f}"))
    log.append(f"완료: 총 {time.time()-T0:.0f}s → {dst}\n결과 폴더: {outdir}")
    save_report()
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n완료 ({time.time()-T0:.0f}s): {dst}")


try:
    main()
except SystemExit as e:
    if e.code not in (None, 0):
        log.append(f"[중단] {e.code}")
        save_report()
    raise
except Exception:
    log.append("[예외]\n" + traceback.format_exc())
    save_report()
    raise
