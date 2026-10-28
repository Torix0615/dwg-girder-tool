"""개발 PC: 서버에 쌓인 피드백(원본·결과·내용 zip)을 내려받아 feedback/<id>/ 에 풀고 INDEX.md 갱신.
python dist_build/pull_feedback.py            # 아직 안 가져온 것만 받고 서버에 '가져감' 표시
python dist_build/pull_feedback.py --all      # 전부 목록(이미 받은 것은 건너뜀)
python dist_build/pull_feedback.py --delete <id>   # 서버에서 삭제
서버 주소·키 = dist_build/secrets.json (feedback_url / feedback_key)
"""
import os, sys, json, zipfile, urllib.request, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
OUT = os.path.join(SRC, "feedback")
sec = json.load(open(os.path.join(HERE, "secrets.json"), encoding="utf-8"))
URL, KEY = sec["feedback_url"].rstrip("/"), sec["feedback_key"]


def req(path, method="GET", data=None):
    r = urllib.request.Request(URL + path, method=method, data=data, headers={"x-key": KEY})
    return urllib.request.urlopen(r, timeout=600)


def main():
    argv = sys.argv[1:]
    if "--delete" in argv:
        fid = argv[argv.index("--delete") + 1]
        print(req(f"/api/feedback/{fid}", "DELETE").read().decode()); return
    items = json.loads(req("/api/feedback" + ("?all=1" if "--all" in argv else "")).read().decode())["items"]
    print(f"서버 피드백 {len(items)}건")
    os.makedirs(OUT, exist_ok=True)
    for it in items:
        fid = it["id"]; d = os.path.join(OUT, fid)
        if os.path.isdir(d):
            print(f"  {fid} 이미 있음"); continue
        print(f"  {fid} {it.get('size', 0)/1e6:.1f}MB scope={it.get('scope')} job={it.get('job')} 받는 중…")
        zp = os.path.join(OUT, fid + ".zip")
        with req(f"/api/feedback/{fid}.zip") as r, open(zp, "wb") as f:
            while True:
                c = r.read(1 << 20)
                if not c:
                    break
                f.write(c)
        try:
            with zipfile.ZipFile(zp) as z:
                z.extractall(d)
        except zipfile.BadZipFile:
            print(f"  {fid} zip 아님 → 서버에서 삭제"); os.remove(zp); req(f"/api/feedback/{fid}", "DELETE"); continue
        os.remove(zp)
        json.dump(it, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        req(f"/api/feedback/{fid}/done", "POST", b"")
    # INDEX.md
    rows = []
    for fid in sorted(os.listdir(OUT)):
        d = os.path.join(OUT, fid)
        if not os.path.isdir(d):
            continue
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "meta.json")) else {}
        txt = open(os.path.join(d, "피드백.txt"), encoding="utf-8").read() if os.path.exists(os.path.join(d, "피드백.txt")) else ""
        body = txt.split("[내용]", 1)[-1]
        body = body.split("\n\n", 1)[-1] if "\n\n" in body else body  # 구분·대상 도면 머리글 다음이 본문
        body = body.strip().replace("\n", " ")[:120]
        files = ", ".join(sorted(os.listdir(os.path.join(d, "files")))) if os.path.isdir(os.path.join(d, "files")) else "-"
        verdict = open(os.path.join(d, "판정.md"), encoding="utf-8").read().splitlines()[0] if os.path.exists(os.path.join(d, "판정.md")) else "(미판정)"
        kind = "오류보고" if meta.get("kind") == "error" else "피드백"
        rows.append(f"| {fid} | {kind} | {meta.get('scope', '-')} | {meta.get('job', '-')} | {body} | {verdict} |")
    with open(os.path.join(OUT, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# 피드백·오류보고 목록\n\n판정은 각 폴더의 판정.md 첫 줄(공통 규칙 → 코드 반영 / 이 도면 전용 / 보류). 오류보고는 재현 후 코드 수정이 원칙. 절차는 docs/FEEDBACK_LOOP.md\n\n")
        f.write("| id | 종류 | 구분 | 도면 | 내용 | 판정 |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    print(f"INDEX 갱신: {os.path.join(OUT, 'INDEX.md')} ({len(rows)}건)")


if __name__ == "__main__":
    main()
