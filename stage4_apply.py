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
used_names = set()
for i in sec_lines.values():
    parts = [p.strip() for p in src[i].split(",")]
    if len(parts) > 2:
        used_names.add(parts[2])

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
        name = f"{PREFIX[kind]}{counter[kind]}"
        if name not in used_names:
            used_names.add(name); break
    # SB 치수: 'SB' 토큰 뒤 '2', H, B
    try:
        si = next(j for j, p in enumerate(parts) if p.upper() == "SB")
        parts[si + 2] = str(H); parts[si + 3] = str(B)
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

out = src[:sec_end] + [v[2] for v in new_secs.values()] + src[sec_end:]
head = [f";  4단계 구조 검토 승인 반영 {time.strftime('%Y/%m/%d %H:%M')} — 단면 치수 변경 {n_changed}개 요소, 새 단면 {len(new_secs)}개 (철근은 엑셀 참조)"]
if out and out[0].startswith(";"):
    out = out[:1] + head + out[1:]
else:
    out = head + out
open(out_p, "w", encoding="utf-8", newline="\r\n").write("\n".join(out) + "\n")
print(f"수정 MGT 저장: {out_p} (요소 {n_changed}개 단면 교체, 새 단면 {len(new_secs)}개: {', '.join(f'{v[1]} {k[1]}x{k[2]}' for k, v in new_secs.items())})", flush=True)
print("SUMMARY=" + json.dumps({"changed": n_changed, "new_sections": [{"id": v[0], "name": v[1], "kind": k[0], "H": k[1], "B": k[2]} for k, v in new_secs.items()]}, ensure_ascii=False), flush=True)
