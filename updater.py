"""실행 전 자동 업데이트(표준 라이브러리만 사용). 런처 bat 가 파이프라인보다 먼저 호출.
- <루트>/app/version.txt 와 서버 latest.json 의 app_version 비교 → 새 버전이면 변경 내용 출력 후 app.zip 받아 app/ 교체
- runtime_version 이 다르면 runtime.zip 을 <루트>/runtime_new/ 에 풀어 둠 → bat 가 파이썬 종료 후 폴더 교체
- 네트워크 실패 시 메시지만 내고 현재 버전으로 계속(종료 코드 0)
서버 주소: 환경변수 DWG_UPDATE_URL > app/update_source.txt
"""
import os, sys, json, shutil, zipfile, time, urllib.request, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP, RT = os.path.join(ROOT, "app"), os.path.join(ROOT, "runtime")
TIMEOUT = 8


def read(p, default=""):
    try:
        return open(p, encoding="utf-8").read().strip()
    except OSError:
        return default


def vt(s):
    return tuple(int(x) for x in s.strip().lstrip("v").split(".") if x.isdigit()) or (0,)


def download(url, dst, label):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0); got = 0; t = time.time()
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk); got += len(chunk)
            if total and time.time() - t > 1:
                print(f"\r  {label} 다운로드 {got/1e6:.0f}/{total/1e6:.0f} MB", end="", flush=True); t = time.time()
    print(f"\r  {label} 다운로드 완료 {got/1e6:.1f} MB      ")


def extract(zp, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    with zipfile.ZipFile(zp) as z:
        z.extractall(dst)


def ensure_config():
    cfg, default = os.path.join(ROOT, "config.json"), os.path.join(APP, "config.default.json")
    if not os.path.exists(cfg) and os.path.exists(default):
        shutil.copy2(default, cfg)
        print("config.json 을 기본값으로 생성했습니다(규칙값은 이 파일에서 수정).")


def main():
    app_ver = read(os.path.join(APP, "version.txt"), "0")
    rt_ver = read(os.path.join(RT, "runtime_version.txt"), "0")
    url = os.environ.get("DWG_UPDATE_URL") or read(os.path.join(APP, "update_source.txt"))
    print(f"골조·거더·보 생성기 v{app_ver} (런타임 {rt_ver})")
    if not url:
        print("업데이트 서버 주소 없음 → 현재 버전으로 실행"); ensure_config(); return
    try:
        with urllib.request.urlopen(url + ("&" if "?" in url else "?") + f"t={int(time.time())}", timeout=TIMEOUT) as r:
            latest = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"업데이트 확인 실패({type(e).__name__}) → 현재 버전으로 실행"); ensure_config(); return
    new = latest.get("app_version", "0")
    tmp = os.path.join(ROOT, "tmp"); os.makedirs(tmp, exist_ok=True)
    if vt(new) > vt(app_ver):
        print(f"\n새 버전 v{new} 발견 (현재 v{app_ver}). 변경 내용:")
        for n in latest.get("notes", []):
            if vt(n.get("version", "0")) > vt(app_ver):
                print(f"  [v{n['version']} {n.get('date', '')}]")
                for it in n.get("items", []):
                    print(f"   - {it}")
        try:
            zp = os.path.join(tmp, "app.zip")
            download(latest["app_url"], zp, "앱")
            new_dir = os.path.join(ROOT, "app_new"); extract(zp, new_dir)
            if read(os.path.join(new_dir, "version.txt"), "0") != new:
                raise RuntimeError("받은 파일의 버전이 다름")
            old_dir = os.path.join(ROOT, "app_old")
            if os.path.exists(old_dir):
                shutil.rmtree(old_dir)
            os.rename(APP, old_dir); os.rename(new_dir, APP)
            shutil.rmtree(old_dir, ignore_errors=True)
            print(f"앱 v{app_ver} → v{new} 업데이트 완료\n")
        except Exception as e:
            print(f"앱 업데이트 실패({type(e).__name__}: {e}) → 현재 버전으로 실행")
    else:
        print("최신 버전입니다.")
    rt_new = str(latest.get("runtime_version", "0"))
    if vt(rt_new) > vt(rt_ver) and latest.get("runtime_url"):
        print(f"런타임 {rt_ver} → {rt_new} 업데이트(용량이 커서 몇 분 걸릴 수 있음)")
        try:
            zp = os.path.join(tmp, "runtime.zip")
            download(latest["runtime_url"], zp, "런타임")
            new_dir = os.path.join(ROOT, "runtime_new"); extract(zp, new_dir)
            if not os.path.exists(os.path.join(new_dir, "python.exe")):
                raise RuntimeError("python.exe 없음")
            print("런타임 준비 완료(이번 실행 직후 교체됨)")
        except Exception as e:
            print(f"런타임 업데이트 실패({type(e).__name__}: {e}) → 현재 런타임으로 실행")
            shutil.rmtree(os.path.join(ROOT, "runtime_new"), ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    ensure_config()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"업데이트 과정 오류({type(e).__name__}: {e}) → 현재 버전으로 실행")
    sys.exit(0)
