"""피드백 zip 만들기: 내용 입력 → 버전·설정·최근 report 로그와 함께 바탕화면에 zip 생성(표준 라이브러리만).
생성된 zip 을 카카오톡/메일로 개발자에게 보내면 됨.
"""
import os, sys, zipfile, time, platform, ctypes, ctypes.wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def desktop():
    buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY(OneDrive 바탕화면 포함)
    return buf.value or os.path.join(os.environ.get("USERPROFILE", "."), "Desktop")


def read(p):
    try:
        return open(p, encoding="utf-8").read().strip()
    except OSError:
        return "(없음)"


def main():
    # 데스크탑 앱에서 호출: --text <파일>(내용) [--extra <파일>](추가 로그) → 대화 없이 생성, 마지막 줄 OUT=경로
    #   --attach <파일>(반복: 원본·결과 DXF 등을 files/ 에 동봉)  --out <zip 경로>(기본: 바탕화면)
    argv = sys.argv[1:]
    text_file = argv[argv.index("--text") + 1] if "--text" in argv else None
    extra_file = argv[argv.index("--extra") + 1] if "--extra" in argv else None
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else None
    attach = [argv[i + 1] for i, a in enumerate(argv) if a == "--attach" and i + 1 < len(argv)]
    if text_file:
        lines = open(text_file, encoding="utf-8-sig").read().splitlines()
    else:
        print("=" * 60)
        print(" 골조·거더·보 생성기 피드백 작성")
        print(" 문제점·보완 요청·바라는 점을 적어 주세요. 한 줄씩 입력, 빈 줄에서 Enter 하면 끝.")
        print("=" * 60)
        lines = []
        while True:
            try:
                s = input("> ")
            except EOFError:
                break
            if s.strip() == "" and lines:
                break
            if s.strip() == "":
                continue
            lines.append(s)
    if not [l for l in lines if l.strip()]:
        print("입력이 없어 취소합니다."); sys.exit(1)
    ver = read(os.path.join(HERE, "version.txt")); rt = read(os.path.join(ROOT, "runtime", "runtime_version.txt"))
    stamp = time.strftime("%Y%m%d_%H%M")
    out = out_path or os.path.join(desktop(), f"골조거더보_피드백_{stamp}.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    head = [f"작성: {time.strftime('%Y-%m-%d %H:%M:%S')}", f"앱 버전: {ver} / 런타임: {rt}",
            f"PC: {platform.node()} {platform.platform()}", "", "[내용]"] + lines
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("피드백.txt", "\n".join(head))
        cfg = os.path.join(ROOT, "config.json")
        if os.path.exists(cfg):
            z.write(cfg, "config.json")
        logs = os.path.join(ROOT, "logs")
        if os.path.isdir(logs):
            for f in sorted(os.listdir(logs))[-10:]:
                z.write(os.path.join(logs, f), "logs/" + f)
        if extra_file and os.path.exists(extra_file):
            z.write(extra_file, "desktop_log.txt")
        for p in attach:
            if os.path.isfile(p):
                z.write(p, "files/" + os.path.basename(p))
    print(f"\n피드백 파일 생성: {out}")
    print("이 파일을 카카오톡 또는 메일로 보내 주세요. 수정되면 다음 실행 때 자동으로 업데이트됩니다.")
    if text_file:
        print(f"OUT={out}")
    else:
        try:
            os.startfile(os.path.dirname(out))
        except OSError:
            pass


if __name__ == "__main__":
    main()
