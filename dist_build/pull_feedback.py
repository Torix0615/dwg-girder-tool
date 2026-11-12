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

# 자동 분류(프로그램 화면·기능 / 생성 규칙·결과) — desktop/renderer/classify.js 와 같은 키워드(두 곳 동시 수정)
UI_STRONG = ['버튼', '레이아웃', '화면', '메뉴', '탭', '패널', '글꼴', '폰트', '글자', '글씨', '색상', '색깔', '테마', '다크', '단축키', '트레이', '아이콘', 'UI', '디자인', '프로그램', '앱 ', '앱이', '앱을', '앱에', '입력창', '입력란', '스크롤', '진행률', '사용성', '불편', '창이', '창을', '창 ', '카드', '사이드바', '목록에서', '마우스', '키보드']
UI_WEAK = ['위치', '배치', '이동', '옮기', '옮겨', '크기', '목록', '정렬', '기능', '표시', '설정', '옵션', '클릭', '드래그', '저장', '다운로드', '열기', '닫기', '보이게', '숨기', '순서', '알림', '업데이트']
RULE_STRONG = ['거더', 'GIRDER', 'BEAM', '기둥', 'COLUMN', '도곽', '레이어', 'LAYER', '중심선', '벽', '층', 'MGT', 'MIDAS', 'DXF', 'DWG', '도면', '블록', '폴리선', '선종류', 'OPEN', 'XREF', '참조', '간섭', '분할', '단면', '치수', '절점', '요소', '규칙', '추출', '인식', '노랑', '빨강', '경고', '비지지', '지지', 'EXPLODE', '베이', '램프', '옥탑', '지하']
KIND_LABEL = {"ui": "프로그램 화면·기능", "rule": "생성 규칙·결과", "unknown": "모름"}


def _hits(text, words):
    up = text.upper()
    return [w for w in words if (w.upper() in up if w.replace(" ", "").isascii() and w.replace(" ", "").isalpha() else w in text)]


def classify(text):
    """→ 'ui' | 'rule' | 'unknown' (classify.js 와 같은 점수 규칙)"""
    text = text or ""
    ui = len(_hits(text, UI_STRONG)) * 2 + len(_hits(text, UI_WEAK))
    rule = len(_hits(text, RULE_STRONG)) * 2
    if ui >= 2 and ui > rule:
        return "ui"
    if rule > 0:
        return "rule"
    return "ui" if ui > 0 else "unknown"


def kind_label(meta, text):
    """INDEX 종류 열: 오류보고 / 프로그램(UI·기능) / 일반(규칙 의견) / 피드백(UI·기능 의심) / 피드백.
    프로그램(UI·기능)·UI 의심 건은 규칙 코드가 아니라 desktop/ 를 고쳐 release.py --shell 로 배포(FEEDBACK_LOOP 2절 '프로그램 변경')."""
    if meta.get("kind") == "error":
        return "오류보고"
    if meta.get("kind") == "sample":  # [건너뛰기] = 결과에 문제 없음으로 표시한 작업(원본·결과 첨부) — 피드백·오류 파일과 견주는 기준 표본
        return "표본(문제 없음)"
    cat = meta.get("category")
    auto = meta.get("category_auto") or classify(text)
    if meta.get("kind") == "general":  # 도면 작업 없이 보낸 피드백(첨부 없음)
        if cat == "ui" or (cat in (None, "unknown") and auto == "ui"):
            return "프로그램(UI·기능)"
        return "일반(규칙 의견)"
    if cat == "ui" or auto == "ui":
        return "피드백(UI·기능 의심)"
    return "피드백"


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
        print(f"  {fid} {it.get('size', 0)/1e6:.1f}MB [{kind_label(it, it.get('text', ''))}] scope={it.get('scope')} job={it.get('job')} 받는 중…")
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
    rows, kinds = [], []
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
        kind = kind_label(meta, meta.get("text") or body)
        if meta.get("kind") == "sample" and verdict == "(미판정)":
            verdict = "표본 — 판정 대상 아님"
        kinds.append((fid, kind, verdict))
        rows.append(f"| {fid} | {kind} | {meta.get('scope', '-')} | {meta.get('job', '-')} | {body} | {verdict} |")
    with open(os.path.join(OUT, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# 피드백·오류보고 목록\n\n판정은 각 폴더의 판정.md 첫 줄(공통 규칙 → 코드 반영 / 이 도면 전용 / 프로그램 변경 / 보류). 오류보고는 재현 후 코드 수정이 원칙. "
                "종류 `표본(문제 없음)` 은 사용자가 [건너뛰기] 로 결과에 문제가 없다고 표시한 작업(판정 대상 아님 — 피드백·오류 파일과 견주는 기준 자료). "
                "종류 `프로그램(UI·기능)`·`피드백(UI·기능 의심)` 은 도면 규칙이 아니라 프로그램 화면·기능 요청 → desktop/ 수정 후 `release.py --shell`. 절차는 docs/FEEDBACK_LOOP.md\n\n")
        f.write("| id | 종류 | 구분 | 도면 | 내용 | 판정 |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    print(f"INDEX 갱신: {os.path.join(OUT, 'INDEX.md')} ({len(rows)}건)")
    prog = [fid for fid, k, v in kinds if "UI" in k and v == "(미판정)"]
    if prog:
        print(f"※ 프로그램(UI·기능) 요청 미판정 {len(prog)}건: {', '.join(prog)} → desktop/ 수정 → dev 앱 화면 확인 → release.py <버전> ... --shell")


if __name__ == "__main__":
    main()
