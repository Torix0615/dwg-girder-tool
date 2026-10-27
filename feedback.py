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
    if not lines:
        print("입력이 없어 취소합니다."); return
    ver = read(os.path.join(HERE, "version.txt")); rt = read(os.path.join(ROOT, "runtime", "runtime_version.txt"))
    stamp = time.strftime("%Y%m%d_%H%M")
    out = os.path.join(desktop(), f"골조거더보_피드백_{stamp}.zip")
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
    print(f"\n피드백 파일 생성: {out}")
    print("이 파일을 카카오톡 또는 메일로 보내 주세요. 수정되면 다음 실행 때 자동으로 업데이트됩니다.")
    try:
        os.startfile(os.path.dirname(out))
    except OSError:
        pass


if __name__ == "__main__":
    main()
