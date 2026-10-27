"""1단계 후보 선별: 원본(d1.pkl) 모델공간 전개 프리미티브를 층별로 나누고 범주(골조/중심선/OPEN)로 분류해 저장.
python stage1_select.py out/d1.pkl out/s1_cand.pkl
"""
import sys, re, pickle, collections
import numpy as np

from cfg import pop_config_arg
CFG, argv = pop_config_arg(sys.argv[1:])
src, out = argv[0], argv[1]
d = pickle.load(open(src, "rb"))
msp = d["msp"]

# 층 띠: 층 평면도 블록 INSERT y (상단) 기준, 층 간격은 설정값 또는 INSERT y 간격 중앙값
FLOOR_RE = CFG["층_블록_정규식"]
FY = {}
for i in d["inserts"]:
    m = re.match(FLOOR_RE, i["name"])
    if m:
        FY[int(m.group(1))] = i["y"]
if not FY:
    raise SystemExit(f"층 블록을 찾지 못함: 정규식 {FLOOR_RE!r} 에 맞는 INSERT 가 모델공간에 없음 (config.json 의 층_블록_정규식 확인)")
H = float(CFG["층_간격"]) or 0.0
if H <= 0:
    ys = sorted(FY.values(), reverse=True)
    H = float(np.median(np.diff(ys)) * -1) if len(ys) > 1 else 1e9
print("floor tops:", FY, "spacing:", H)
GOLF_L = set(CFG["골조_레이어"]); GOLF_C = int(CFG["골조_색"]); CEN_L = set(CFG["중심선_레이어"]); OPEN_L = CFG["OPEN_레이어"]; DEF_L = CFG["동_벽체_레이어"]


def pt_y(p):
    k = p["kind"]
    if k == "LINE": return (p["y1"] + p["y2"]) / 2
    if k == "POLY": return sum(q[1] for q in p["pts"]) / len(p["pts"])
    if k in ("ARC", "CIRCLE"): return p["cy"]
    return p.get("y", 0.0)


def floor_of(p):
    if p["path"]:
        m = re.match(r"지하(\d)층 주차장 평면도$", p["path"][0])
        if m: return int(m.group(1))
    y = pt_y(p)
    for n, fy in FY.items():
        if fy - H < y <= fy: return n
    return 0


GEOM = ("LINE", "POLY", "ARC", "CIRCLE")
cand = {n: {"golf": [], "cen": [], "open": [], "open_text": [], "wallb": [], "text": [], "def": []} for n in FY}
stat = collections.Counter()
for p in msp:
    n = floor_of(p)
    if n == 0:
        continue
    k = p["kind"]; ly = p["layer"]
    if k in GEOM and p["color"] == GOLF_C and p["lcolor"] == GOLF_C and (ly in GOLF_L or ly == CFG["기둥_레이어"]):
        cand[n]["golf"].append(p); stat[(n, "golf", ly)] += 1
    elif k in GEOM and p["color"] == GOLF_C and p["lcolor"] == GOLF_C:
        stat[(n, "golf-제외(설정 밖 레이어)", ly)] += 1
    elif k in GEOM and ly in CEN_L:
        cand[n]["cen"].append(p); stat[(n, "cen", ly)] += 1
    elif k in GEOM and ly == OPEN_L:
        cand[n]["open"].append(p); stat[(n, "open", ly)] += 1
    elif k == "TEXT" and re.search(r"OPEN", p["s"], re.I):
        cand[n]["open_text"].append(p); stat[(n, "open_text", ly)] += 1
    elif k in GEOM and ly == DEF_L:
        cand[n]["def"].append(p)
    elif k in GEOM and ly == "WALL-B":
        cand[n]["wallb"].append(p)
    elif k == "TEXT" and ly in ("text-1", "TEXT-설비", "TEXT-LEVEL", "CHECK-지하주차장 기둥"):
        cand[n]["text"].append(p)

for n in sorted(cand):
    print(f"B{n}: " + ", ".join(f"{c}={len(v)}" for c, v in cand[n].items()))
for k, v in sorted(stat.items()):
    print("  ", k, v)
pickle.dump({"FY": FY, "H": H, "cand": cand, "cfg": CFG}, open(out, "wb"), protocol=5)
print("saved", out)
