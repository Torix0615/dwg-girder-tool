"""외부 MIDAS Gen MGT(전문가가 만든 모델) → 4단계 요소 대응표(_elements.json) 변환.
python mgt_import.py <모델.mgt> <출력 _elements.json>
 - 3단계(stage3_mgt.py)가 만드는 대응표와 같은 형식(kN·mm)으로 써서 stage4_check / stage4_selftest 에 그대로 넣는다.
 - *UNIT 의 길이 단위(M/CM/MM)를 읽어 mm 로 환산. 더미 재료·단면(9999, 이름 Dummy)과 BEAM 이 아닌 요소는 제외.
 - 종류: 수직(길이의 70% 이상이 Z 방향) = 기둥, 수평은 단면명 첫 글자(C/G/B) → 기둥/거더/보, 그 외 = 거더.
 - 층: *STORY 레벨 중 요소 아래 절점 z 이하의 가장 높은 층(없으면 'F0'). 층고 = 층 레벨 간격의 최빈값.
 - 첫 실제 샘플: 피드백 1d7f01 답변 5 샘플(250930 흑석동 어린이집, KN·M, C1(500x500)/G1(400x600)/B1(400x600), 2026-11-10).
"""
import sys, re, json, collections

if len(sys.argv) < 3:
    sys.exit(__doc__)
mgt_p, out_p = sys.argv[1], sys.argv[2]
raw = open(mgt_p, "rb").read()
for enc in ("utf-8-sig", "cp949", "latin-1"):
    try:
        text = raw.decode(enc); break
    except UnicodeDecodeError:
        continue

# 섹션 분리
blocks = collections.OrderedDict()
cur = None
for l in text.splitlines():
    s = l.strip()
    if not s or s.startswith(";"):
        continue
    if s.startswith("*"):
        cur = s[1:].split(";")[0].split(",")[0].strip().upper()
        blocks.setdefault(cur, [])
        continue
    if cur:
        blocks[cur].append(s.split(";")[0].rstrip())


def cells(line):
    return [c.strip() for c in line.split(",")]


# 단위
scale = 1.0
if blocks.get("UNIT"):
    u = cells(blocks["UNIT"][0])
    lu = (u[1] if len(u) > 1 else "MM").upper()
    scale = {"MM": 1.0, "CM": 10.0, "M": 1000.0, "IN": 25.4, "FT": 304.8}.get(lu, 1.0)
    force_u = u[0].upper() if u else "KN"
else:
    lu, force_u = "MM", "KN"

# 절점
nodes = {}
for l in blocks.get("NODE", []):
    c = cells(l)
    try:
        nodes[int(c[0])] = (float(c[1]) * scale, float(c[2]) * scale, float(c[3]) * scale)
    except (ValueError, IndexError):
        continue

# 재료(fck 는 이름 C30 → 30)
materials = {}
for l in blocks.get("MATERIAL", []):
    c = cells(l)
    try:
        mid = int(c[0])
    except ValueError:
        continue
    name = c[2] if len(c) > 2 else ""
    m = re.search(r"C\s*(\d{2,3})", name, re.I)
    materials[mid] = {"name": name, "fck": int(m.group(1)) if m else None, "dummy": name.lower() == "dummy" or mid == 9999}

# 단면(SB 직사각형: 'SB' 토큰 뒤 2, H, B)
sections = {}
for l in blocks.get("SECTION", []):
    c = cells(l)
    try:
        sid = int(c[0])
    except ValueError:
        continue  # 2줄 이상 단면(VALUE 형식)의 뒷줄
    name = c[2] if len(c) > 2 else ""
    H = B = None
    try:
        si = next(j for j, p in enumerate(c) if p.upper() == "SB")
        H = float(c[si + 2]) * scale; B = float(c[si + 3]) * scale
    except (StopIteration, IndexError, ValueError):
        pass
    sections[sid] = {"name": name, "H": H, "B": B, "dummy": name.lower() == "dummy" or sid == 9999}

# 층
stories = []
for l in blocks.get("STORY", []):
    m = re.match(r"NAME\s*=\s*([^,]+),\s*([-+\d.eE]+)", l.strip(), re.I)
    if m:
        stories.append({"name": m.group(1).strip(), "z": round(float(m.group(2)) * scale, 1)})
stories.sort(key=lambda s: s["z"])
dz = [round(b["z"] - a["z"]) for a, b in zip(stories, stories[1:]) if b["z"] > a["z"]]
story_h = float(collections.Counter(dz).most_common(1)[0][0]) if dz else 5000.0


def floor_of(z):
    f = None
    for s in stories:
        if s["z"] <= z + 1.0:
            f = s["name"]
    return f or "F0"


def kind_of(sec_name, vertical):
    if vertical:
        return "col"
    ch = (sec_name or "").strip()[:1].upper()
    return {"C": "col", "G": "girder", "B": "beam"}.get(ch, "girder")


elements = []
skipped = collections.Counter()
for l in blocks.get("ELEMENT", []):
    c = cells(l)
    try:
        eid = int(c[0])
    except ValueError:
        continue
    typ = (c[1] if len(c) > 1 else "").upper()
    if typ != "BEAM":
        skipped[typ or "?"] += 1; continue
    try:
        mat, sec, n1, n2 = int(c[2]), int(c[3]), int(c[4]), int(c[5])
    except (ValueError, IndexError):
        skipped["형식"] += 1; continue
    if materials.get(mat, {}).get("dummy") or sections.get(sec, {}).get("dummy"):
        skipped["더미"] += 1; continue
    if n1 not in nodes or n2 not in nodes or sec not in sections or sections[sec]["H"] is None:
        skipped["절점·단면 없음"] += 1; continue
    p, q = nodes[n1], nodes[n2]
    L = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2) ** 0.5
    if L < 1.0:
        skipped["길이 0"] += 1; continue
    vertical = abs(q[2] - p[2]) >= 0.7 * L
    zlow = min(p[2], q[2])
    elements.append({"id": eid, "kind": kind_of(sections[sec]["name"], vertical), "floor": floor_of(zlow), "mat": mat, "sec": sec,
                     "nodes": [n1, n2], "len": round(L, 1), "z": round(zlow, 1)})

if not elements:
    sys.exit("[원인] 입력 — MGT 에서 검토할 BEAM 요소를 찾지 못함(*NODE/*ELEMENT/*SECTION 확인)")
used_secs = {e["sec"] for e in elements}
used_mats = {e["mat"] for e in elements}
out = {
    "version": 1, "unit": {"force": "kN", "length": "mm"}, "story_h": story_h,
    "source": {"file": mgt_p.replace("\\", "/").split("/")[-1], "unit": f"{force_u}, {lu}", "importer": "mgt_import"},
    "materials": {str(k): {"name": v["name"], "fck": v["fck"]} for k, v in materials.items() if k in used_mats},
    "sections": {str(k): {"name": v["name"], "H": round(v["H"]), "B": round(v["B"])} for k, v in sections.items() if k in used_secs},
    "stories": stories or [{"name": "F0", "z": 0.0}],
    "elements": elements,
}
json.dump(out, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
n = collections.Counter(e["kind"] for e in elements)
nofck = [v["name"] for k, v in materials.items() if k in used_mats and v["fck"] is None]
print(f"요소 대응표 저장: {out_p} — 단위 {force_u}·{lu}(×{scale:g}→mm), 요소 {len(elements)}개(기둥 {n['col']} 거더 {n['girder']} 보 {n['beam']}), "
      f"단면 {len(out['sections'])}개 {', '.join(f'{v['name']} H{v['H']}×B{v['B']}' for v in out['sections'].values())}, "
      f"층 {len(stories)}개(층고 {story_h:g}), 제외 {dict(skipped) or '없음'}" + (f", fck 미상 재료 {nofck}" if nofck else ""), flush=True)
print("SUMMARY=" + json.dumps({"elements": len(elements), "col": n["col"], "girder": n["girder"], "beam": n["beam"], "sections": len(out["sections"]),
                              "stories": len(stories), "scale": scale, "skipped": dict(skipped)}, ensure_ascii=False), flush=True)
