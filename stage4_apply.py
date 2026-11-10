"""4단계 승인: 검토 추천(check.json)대로 단면 치수만 바꾼 수정 MGT 작성(철근은 쓰지 않음 — 전문가 답변 5).
python stage4_apply.py <원본 .mgt> <check.json> <출력 .mgt>
 - 치수가 바뀐 요소를 (종류, H, B) 같은 것끼리 묶어 새 *SECTION(C2·C3…, G2…, B2…) 을 추가하고 *ELEMENT 의 iPRO 만 바꾼다. 나머지 줄은 그대로.
 - 치수 변경이 없으면 원본과 같은 내용(머리말 주석만 추가). 마지막 줄 SUMMARY=<json>.
"""
import sys, re, json, time

if len(sys.argv) < 4:
    sys.exit(__doc__)
mgt_p, chk_p, out_p = sys.argv[1:4]
src = open(mgt_p, encoding="utf-8", errors="replace").read().splitlines()
chk = json.load(open(chk_p, encoding="utf-8"))
PREFIX = {"col": "C", "girder": "G", "beam": "B"}
BASE_ID = {"col": 10, "girder": 100, "beam": 500}

# *UNIT 길이 단위: 추천 치수(mm)를 원본 MGT 단위로 써야 함(전문가 실제 모델은 KN·M — 1d7f01 답변 5 샘플, 2026-11-10)
LEN_UNIT = "MM"
u_i = next((i for i, l in enumerate(src) if l.strip().upper().startswith("*UNIT")), None)
if u_i is not None:
    for l in src[u_i + 1:u_i + 6]:
        s = l.strip()
        if s and not s.startswith(";") and not s.startswith("*"):
            parts = [p.strip().upper() for p in s.split(",")]
            if len(parts) > 1:
                LEN_UNIT = parts[1]
            break
MM_PER = {"MM": 1.0, "CM": 10.0, "M": 1000.0, "IN": 25.4, "FT": 304.8}.get(LEN_UNIT, 1.0)


def dim_txt(mm):
    v = mm / MM_PER
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:.6g}"

# 바꿀 요소: 추천이 있고 치수가 바뀐 것만
changes = {}
for r in chk["results"]:
    rec = r.get("rec")
    if r.get("status") == "ng" and rec and rec.get("dims_changed"):
        changes[int(r["id"])] = (r["kind"], int(round(rec["H"])), int(round(rec["B"])), int(r["sec"]))

# *SECTION 블록 찾기
sec_start = next((i for i, l in enumerate(src) if l.strip().upper().startswith("*SECTION")), None)
if sec_start is None:
    sys.exit("원본 MGT 에 *SECTION 이 없음")
sec_end = sec_start + 1
while sec_end < len(src) and not src[sec_end].strip().startswith("*"):
    sec_end += 1
sec_lines = {}
for i in range(sec_start + 1, sec_end):
    l = src[i]
    if l.strip() and not l.strip().startswith(";"):
        m = re.match(r"\s*(\d+)\s*,", l)
        if m:
            sec_lines[int(m.group(1))] = i
used_ids = set(sec_lines)
used_names = set()   # 전체 이름(G1(400x600)) 과 번호 부분(G1) 둘 다 — 전문가 모델의 G2(500x600) 가 있으면 새 단면은 G2 를 건너뜀
for i in sec_lines.values():
    parts = [p.strip() for p in src[i].split(",")]
    if len(parts) > 2:
        used_names.add(parts[2]); used_names.add(parts[2].split("(")[0].strip())

new_secs = {}  # (kind,H,B) -> (new id, name, line)
counter = {k: 1 for k in PREFIX}
for eid, (kind, H, B, base_sec) in sorted(changes.items()):
    key = (kind, H, B)
    if key in new_secs:
        continue
    base_i = sec_lines.get(base_sec)
    if base_i is None:
        base_i = sec_lines.get(BASE_ID[kind]) or next(iter(sec_lines.values()))
    parts = [p.strip() for p in src[base_i].split(",")]
    nid = BASE_ID[kind] + 1
    while nid in used_ids:
        nid += 1
    used_ids.add(nid)
    while True:
        counter[kind] += 1
        base = f"{PREFIX[kind]}{counter[kind]}"
        name = f"{base}({B}x{H})"  # 전문가 모델 표기(폭x춤, 예 G1(400x600))와 같게
        if name not in used_names and base not in used_names:
            used_names.add(name); used_names.add(base); break
    # SB 치수: 'SB' 토큰 뒤 '2', H, B — 원본 MGT 길이 단위로
    try:
        si = next(j for j, p in enumerate(parts) if p.upper() == "SB")
        parts[si + 2] = dim_txt(H); parts[si + 3] = dim_txt(B)
    except (StopIteration, IndexError):
        sys.exit(f"단면 {base_sec} 줄에서 SB 치수를 찾지 못함: {src[base_i]}")
    parts[0] = f"{nid:>5}"; parts[2] = name
    new_secs[key] = (nid, name, ", ".join(parts))

# *ELEMENT 의 iPRO 교체
el_start = next((i for i, l in enumerate(src) if l.strip().upper().startswith("*ELEMENT")), None)
if el_start is None:
    sys.exit("원본 MGT 에 *ELEMENT 가 없음")
el_end = el_start + 1
while el_end < len(src) and not src[el_end].strip().startswith("*"):
    el_end += 1
n_changed = 0
for i in range(el_start + 1, el_end):
    l = src[i]
    if not l.strip() or l.strip().startswith(";"):
        continue
    parts = [p.strip() for p in l.split(",")]
    try:
        eid = int(parts[0])
    except ValueError:
        continue
    if eid in changes and len(parts) > 3:
        kind, H, B, _ = changes[eid]
        parts[3] = str(new_secs[(kind, H, B)][0])
        src[i] = "   " + ", ".join(parts)
        n_changed += 1

new_lines = [v[2] for v in new_secs.values()]
out = src[:sec_end] + new_lines + src[sec_end:]
# 전문가 모델에는 설계 단면 블록(*DGN-SECT, *SECTION 과 같은 줄)이 따로 있음 — 있으면 거기에도 추가해 설계 단면이 비지 않게
dg_start = next((i for i, l in enumerate(out) if l.strip().upper().startswith("*DGN-SECT")), None)
if dg_start is not None and new_lines:
    dg_end = dg_start + 1
    while dg_end < len(out) and not out[dg_end].strip().startswith("*"):
        dg_end += 1
    while dg_end > dg_start + 1 and not out[dg_end - 1].strip():
        dg_end -= 1
    out = out[:dg_end] + new_lines + out[dg_end:]
head = [f";  4단계 구조 검토 승인 반영 {time.strftime('%Y/%m/%d %H:%M')} — 단면 치수 변경 {n_changed}개 요소, 새 단면 {len(new_secs)}개, 치수 단위 {LEN_UNIT} (철근은 엑셀 참조)"]
if out and out[0].startswith(";"):
    out = out[:1] + head + out[1:]
else:
    out = head + out
open(out_p, "w", encoding="utf-8", newline="\r\n").write("\n".join(out) + "\n")
print(f"수정 MGT 저장: {out_p} (요소 {n_changed}개 단면 교체, 새 단면 {len(new_secs)}개: {', '.join(f'{v[1]} {k[1]}x{k[2]}' for k, v in new_secs.items())})", flush=True)
print("SUMMARY=" + json.dumps({"changed": n_changed, "new_sections": [{"id": v[0], "name": v[1], "kind": k[0], "H": k[1], "B": k[2]} for k, v in new_secs.items()]}, ensure_ascii=False), flush=True)
