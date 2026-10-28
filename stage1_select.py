"""1단계 후보 선별(색 기준·도면 공통 규칙): 원본 전개 프리미티브(d1.pkl)를 층으로 나누고 골조/기둥/중심선/OPEN 으로 분류.
python stage1_select.py out/d1.pkl out/s1_cand.pkl [--config config.json]
규칙(사용자 명령문):
 1. 골조 = 유효색이 골조_색(노랑 2)인 선·폴리선·호 (벽체·기둥). 제외_레이어_정규식(마감·해치·문자 등)은 뺀다.
 2. 기둥 = 골조 중 닫힌 4각 폴리선 또는 4개 선분이 만드는 직사각형(한 변 150~2500mm).
 3. 중심선 = 유효색이 중심선_색(빨강 1)인 선·호. (중심선_구조만=true 면 벽·기둥 위를 지나는 것만)
 4. OPEN = 'OPEN' 문자 + 그 둘레의 X 표시(대각선) + 같은 레이어의 둘레 선.
 층 = 골조·중심선 덩어리(층_분리_간격 이상 떨어지면 다른 덩어리)를 가장 가까운 '…평면도' 제목 문자로 이름 붙임.
 저장: {"floors": [{id, label, anchor, bbox, n}], "cand": {id: {golf, cols, cen, open, open_text, def, text}}, "FY", "H"(호환)}
"""
import sys, re, pickle, collections, math
import numpy as np
from scipy import ndimage

from cfg import pop_config_arg
CFG, argv = pop_config_arg(sys.argv[1:])
src, out = argv[0], argv[1]
d = pickle.load(open(src, "rb"))
msp = d["msp"]
GOLF_C, CEN_C = int(CFG["골조_색"]), int(CFG["중심선_색"])
EXCL = re.compile(CFG["제외_레이어_정규식"], re.I) if CFG.get("제외_레이어_정규식") else None
TITLE_RE = re.compile(CFG["층_제목_정규식"])
GAP = float(CFG["층_분리_간격"])
GEOM = ("LINE", "POLY", "ARC", "CIRCLE")


def rep_pts(p):
    k = p["kind"]
    if k == "LINE":
        return [(p["x1"], p["y1"]), (p["x2"], p["y2"])]
    if k == "POLY":
        return [(q[0], q[1]) for q in p["pts"]]
    if k in ("ARC", "CIRCLE"):
        return [(p["cx"], p["cy"])]
    return [(p["x"], p["y"])]


def center(p):
    pts = rep_pts(p)
    return (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))


def excluded(p):
    return EXCL is not None and EXCL.search(p["layer"]) is not None


# ---------- 1. 층 덩어리 ----------
# 층 덩어리는 골조(노랑)만으로 만든다(중심선·도로축선은 층 사이를 이어 붙이므로 제외)
struct_idx = [i for i, p in enumerate(msp) if p["kind"] in GEOM and p["color"] == GOLF_C and not excluded(p)]
if not struct_idx:
    raise SystemExit("골조(노랑) 색의 선이 없음 — 외부참조(XREF) 파일이 빠졌거나 도면 색 규칙(config 골조_색)이 다름")
C = np.array([center(msp[i]) for i in struct_idx])
cx0, cy0 = C.min(axis=0)
cell = np.floor((C - [cx0, cy0]) / GAP).astype(int)
W, Hh = cell.max(axis=0) + 3
grid = np.zeros((Hh, W), dtype=bool)
grid[cell[:, 1] + 1, cell[:, 0] + 1] = True
lab, ncomp = ndimage.label(grid, structure=np.ones((3, 3)))
comp_of = lab[cell[:, 1] + 1, cell[:, 0] + 1]
sizes = np.bincount(comp_of)[1:]
big = max(sizes.max(), 1)
comps = {}
for c in range(1, ncomp + 1):
    m = comp_of == c
    pts = C[m]
    comps[c] = {"n": int(m.sum()), "bbox": (*pts.min(axis=0), *pts.max(axis=0)), "cen": pts.mean(axis=0), "idx": [struct_idx[i] for i in np.nonzero(m)[0]]}
# 작은 덩어리(2% 미만)는 가까운 큰 덩어리(5×간격 안)에 합치고, 아니면 버림
bigs = [c for c in comps if comps[c]["n"] >= 0.02 * big]
dropped = 0
for c in list(comps):
    if c in bigs:
        continue
    best, bd = None, None
    for b in bigs:
        x0, y0, x1, y1 = comps[b]["bbox"]
        p = comps[c]["cen"]
        dx = max(x0 - p[0], 0, p[0] - x1); dy = max(y0 - p[1], 0, p[1] - y1)
        dd = math.hypot(dx, dy)
        if bd is None or dd < bd:
            best, bd = b, dd
    if best is not None and bd <= 5 * GAP:
        comps[best]["idx"] += comps[c]["idx"]; comps[best]["n"] += comps[c]["n"]
    else:
        dropped += comps[c]["n"]
    del comps[c]

# ---------- 2. 층 제목 ----------
def parse_level(s):
    t = s.replace(" ", "")
    if re.search(r"옥탑지붕|지붕층|ROOF", t, re.I):
        return 101
    if re.search(r"옥탑|PH", t):
        return 100
    if re.search(r"PIT", t, re.I):
        return None  # 위치(시트 순서)로 끼워 넣음
    m = re.search(r"지하(\d+)|B(\d+)", t)
    if m:
        return -int(m.group(1) or m.group(2))
    m = re.search(r"(?:지상)?(\d+)(?:~\d+)?층|(\d+)F", t)
    if m:
        return int(m.group(1) or m.group(2))
    return None


titles = []
for p in msp:
    if p["kind"] == "TEXT" and TITLE_RE.search(p["s"]) and not re.search(r"참조|NOTE|주\s*[:：]|우선|범례", p["s"]):
        lv = parse_level(p["s"])
        if lv is None and not re.search(r"PIT|피트|옥탑|지붕|ROOF|기준층|층", p["s"], re.I):
            continue  # 층 표시가 없는 '…평면도' 문자(도면 설명 등)는 제목이 아님
        titles.append({"x": p["x"], "y": p["y"], "h": p.get("h", 0), "s": p["s"].strip(), "level": lv})
T = np.array([[t["x"], t["y"]] for t in titles]) if titles else np.zeros((0, 2))

floors = {}  # id -> {label, anchor, bbox, idx}
unnamed = 0
for c, cp in sorted(comps.items(), key=lambda kv: (kv[1]["cen"][0], -kv[1]["cen"][1])):
    x0, y0, x1, y1 = cp["bbox"]
    lim = 1.5 * max(x1 - x0, y1 - y0) + 20000
    tid = None
    if len(T):
        dd = np.hypot(T[:, 0] - cp["cen"][0], T[:, 1] - cp["cen"][1])
        j = int(np.argmin(dd))
        if dd[j] <= lim:
            tid = j
    if tid is None:
        unnamed += 1
        fid = 1000 + unnamed
        f = floors.setdefault(fid, {"label": f"F?{unnamed}", "anchor": (x0, y0), "bbox": list(cp["bbox"]), "idx": [], "title": None})
    else:
        t = titles[tid]
        fid = t["level"] if t["level"] is not None else ("?", tid)  # 숫자 없는 제목(PIT 등)은 임시 키
        f = floors.setdefault(fid, {"label": t["s"], "anchor": (t["x"], t["y"]), "bbox": list(cp["bbox"]), "idx": [], "title": t["s"]})
        b = f["bbox"]; f["bbox"] = [min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1)]
    f["idx"] += cp["idx"]

# 제목 없는 작은 덩어리(가장 큰 층의 10% 미만: 범례·상세도 등)는 층으로 치지 않음
_nmax = max(len(f["idx"]) for f in floors.values())
for k in [k for k, f in floors.items() if f.get("title") is None and len(f["idx"]) < 0.1 * _nmax]:
    dropped += len(floors[k]["idx"]); del floors[k]
if not floors:
    raise SystemExit("층 덩어리를 만들지 못함")

# 숫자 없는 층(PIT 등): 기준점 배치 순서(층이 늘어선 축)에서 이웃 층 번호의 중간값으로 끼워 넣음
_unres = [k for k in floors if isinstance(k, tuple)]
if _unres:
    A = np.array([floors[k]["anchor"] for k in floors]); keys = list(floors)
    axis = 0 if np.ptp(A[:, 0]) >= np.ptp(A[:, 1]) else 1
    order_pos = sorted(keys, key=lambda k: floors[k]["anchor"][axis])
    numeric = [k for k in order_pos if not isinstance(k, tuple)]
    if numeric and (np.corrcoef([floors[k]["anchor"][axis] for k in numeric], [float(k) for k in numeric])[0, 1] < 0):
        order_pos = order_pos[::-1]
    for k in _unres:
        i = order_pos.index(k)
        prev = next((order_pos[j] for j in range(i - 1, -1, -1) if not isinstance(order_pos[j], tuple)), None)
        nxt = next((order_pos[j] for j in range(i + 1, len(order_pos)) if not isinstance(order_pos[j], tuple)), None)
        if prev is not None and nxt is not None:
            nid = (float(prev) + float(nxt)) / 2
        elif prev is not None:
            nid = float(prev) + 0.5
        elif nxt is not None:
            nid = float(nxt) - 0.5
        else:
            nid = 1000.0 + i
        while nid in floors:
            nid += 0.01
        floors[nid] = floors.pop(k)


def short_label(fid, label):
    if fid != int(fid):  # 끼워 넣은 층(PIT 등): 제목에서 이름
        m = re.search(r"(PIT|[A-Za-z가-힣]+)\s*층?", label.replace("평면도", ""))
        return (m.group(1) if m else label).strip()[:8]
    fid = int(fid)
    if fid <= -1: return f"B{-fid}"
    if fid == 100: return "PH"
    if fid == 101: return "PH-R"
    if fid >= 1000: return label
    m = re.search(r"(\d+\s*~\s*\d+)층", label.replace(" ", ""))
    return f"{m.group(1).replace(' ', '')}F" if m else f"{fid}F"


# ---------- 3. 층별 분류 ----------
def floor_lookup():
    """모든 프리미티브를 층 bbox(여유 GAP) 로 배정: 대표점이 들어가는 bbox 중 가장 가까운 중심"""
    boxes = {fid: f["bbox"] for fid, f in floors.items()}
    def which(p):
        x, y = center(p)
        best, bd = None, None
        for fid, (x0, y0, x1, y1) in boxes.items():
            if x0 - GAP <= x <= x1 + GAP and y0 - GAP <= y <= y1 + GAP:
                dd = math.hypot(x - (x0 + x1) / 2, y - (y0 + y1) / 2)
                if bd is None or dd < bd:
                    best, bd = fid, dd
        return best
    return which


which = floor_lookup()
cand = {fid: {"golf": [], "cols": [], "cen": [], "open": [], "open_text": [], "def": [], "text": []} for fid in floors}
# 층별 블록 인스턴스 수(반복 삽입되는 부품 블록: 세대·기둥·기호 → 그 안의 중심선은 축선이 아니므로 제외)
REPEAT_MIN = int(CFG.get("중심선_반복블록_기준", 2))
EXCL_REPEAT = bool(CFG.get("중심선_반복블록_제외", True))
COMP_RATIO = float(CFG.get("부품블록_크기비율", 0.3))
inst_by_floor = {fid: collections.Counter() for fid in floors}
inst_all = collections.Counter()
inst_size = {}  # 블록 이름 → 내용 범위 최대(w, h)
for p in msp:
    if p["kind"] == "INSTANCE":
        inst_all[p["name"]] += 1
        w, h = p.get("w", 0.0), p.get("h", 0.0)
        pw, ph = inst_size.get(p["name"], (0.0, 0.0))
        inst_size[p["name"]] = (max(pw, w), max(ph, h))
        fid = which(p)
        if fid is not None:
            inst_by_floor[fid][p["name"]] += 1


def in_repeated_block(p, fid):
    """부품 블록(세대·기둥·기호) 안이면 True: 최상위 컨테이너(path[0])를 뺀 경로의 블록이
    도면 전체 또는 이 층에서 2회 이상 삽입되고, 내용 크기가 층 범위의 부품블록_크기비율(30%) 미만."""
    x0, y0, x1, y1 = floors[fid]["bbox"]
    fw, fh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    for n in p["path"][1:]:
        rep = inst_all.get(n, 0) >= REPEAT_MIN or inst_by_floor[fid].get(n, 0) >= REPEAT_MIN
        w, h = inst_size.get(n, (fw, fh))
        if rep and w < COMP_RATIO * fw and h < COMP_RATIO * fh:
            return True
    return False
stat = collections.Counter()
DEF_L = CFG.get("동_벽체_레이어") or None
LABEL_L = CFG.get("기둥_라벨_레이어") or None
open_texts = []
OPEN_LAYER = re.compile(CFG.get("OPEN_레이어_정규식") or "OPEN", re.I)
CEN_LT = re.compile(CFG.get("중심선_선종류_정규식") or "CEN|CENTER|DASHDOT|ISO04", re.I)
CEN_LAYER = re.compile(CFG.get("중심선_레이어_정규식") or "CEN|AXIS|GRID", re.I)
CEN_COLOR_REQ = bool(CFG.get("중심선_색_필수", True))


def is_cen(p):
    """중심선 = (선종류가 일점쇄선 계열 또는 레이어명이 CEN/AXIS/GRID) 이고 (중심선_색_필수면) 유효색이 빨강. 제외 레이어는 뺌."""
    if excluded(p):
        return False
    if not (CEN_LT.search(p.get("lt", "")) or CEN_LAYER.search(p["layer"])):
        return False
    return (not CEN_COLOR_REQ) or p["color"] == CEN_C
for i, p in enumerate(msp):
    k = p["kind"]
    if k == "TEXT":
        if re.search(r"OPEN", p["s"], re.I):
            fid = which(p)
            if fid is not None:
                cand[fid]["open_text"].append(p); open_texts.append((fid, p))
        elif LABEL_L and p["layer"] == LABEL_L:
            fid = which(p)
            if fid is not None:
                cand[fid]["text"].append(p)
        continue
    if k not in GEOM:
        continue
    fid = which(p)
    if fid is None:
        continue
    if OPEN_LAYER.search(p["layer"]):  # OPEN 이름 레이어의 도형(X 표시·둘레)은 그대로
        cand[fid]["open"].append(p); stat[(fid, "open", p["layer"])] += 1
    elif p["color"] == GOLF_C and not excluded(p):
        cand[fid]["golf"].append(p); stat[(fid, "golf", p["layer"])] += 1
    elif p["color"] == GOLF_C:
        stat[(fid, "골조색-제외레이어", p["layer"])] += 1
    elif is_cen(p):
        if EXCL_REPEAT and in_repeated_block(p, fid):
            stat[(fid, "cen-반복블록제외", p["path"][-1][-30:])] += 1
        else:
            cand[fid]["cen"].append(p); stat[(fid, "cen", p["layer"])] += 1
    elif DEF_L and p["layer"] == DEF_L:
        cand[fid]["def"].append(p)


# ---------- 4. 기둥(직사각형) ----------
def rect_from_pts(P):
    P = np.array(P[:4], dtype=float)
    e0, e1 = P[1] - P[0], P[2] - P[1]
    l0, l1 = np.linalg.norm(e0), np.linalg.norm(e1)
    if min(l0, l1) < 150 or max(l0, l1) > 2500:
        return None
    if abs(np.dot(e0, e1)) > 0.02 * l0 * l1:  # 직각 아님
        return None
    e2 = P[3] - P[2]
    if abs(np.linalg.norm(e2) - l0) > 0.05 * l0:
        return None
    return P


def find_rects(golf):
    rects = []
    for p in golf:  # 닫힌 폴리선
        if p["kind"] == "POLY" and p.get("closed") and len(p["pts"]) in (4, 5) and all(abs(q[2]) < 1e-9 for q in p["pts"][:4]):
            P = rect_from_pts([(q[0], q[1]) for q in p["pts"]])
            if P is not None:
                rects.append(P)
    # 4개 선분이 만드는 직사각형
    segs = [(p["x1"], p["y1"], p["x2"], p["y2"]) for p in golf if p["kind"] == "LINE"]
    keyf = lambda x, y: (round(x), round(y))
    ends = collections.defaultdict(list)
    L = []
    for i, s in enumerate(segs):
        l = math.hypot(s[2] - s[0], s[3] - s[1])
        L.append(l)
        if 150 <= l <= 2500:
            ends[keyf(s[0], s[1])].append(i); ends[keyf(s[2], s[3])].append(i)
    seen = set()
    def other(i, k):
        s = segs[i]
        return (s[2], s[3]) if keyf(s[0], s[1]) == k else (s[0], s[1])
    def perp(i, j):
        a = segs[i]; b = segs[j]
        ax, ay = a[2] - a[0], a[3] - a[1]; bx, by = b[2] - b[0], b[3] - b[1]
        return abs(ax * bx + ay * by) <= 0.02 * L[i] * L[j]
    for i in range(len(segs)):
        if not (150 <= L[i] <= 2500):
            continue
        p0 = (segs[i][0], segs[i][1]); p1 = (segs[i][2], segs[i][3])
        for j in ends[keyf(*p1)]:
            if j == i or not perp(i, j):
                continue
            p2 = other(j, keyf(*p1))
            for k in ends[keyf(*p2)]:
                if k in (i, j) or not perp(j, k):
                    continue
                p3 = other(k, keyf(*p2))
                for m_ in ends[keyf(*p3)]:
                    if m_ in (i, j, k) or keyf(*other(m_, keyf(*p3))) != keyf(*p0):
                        continue
                    key = tuple(sorted((i, j, k, m_)))
                    if key in seen:
                        continue
                    seen.add(key)
                    P = rect_from_pts([p0, p1, p2, p3])
                    if P is not None:
                        rects.append(P)
    # 중복(같은 중심) 제거
    outr, cs = [], []
    for P in rects:
        c = P.mean(axis=0)
        if any(np.hypot(c[0] - q[0], c[1] - q[1]) < 50 for q in cs):
            continue
        cs.append(c); outr.append(P)
    return outr


def cen_structural(cen, golf_segs, rects):
    """중심선 중 벽(양쪽 400mm 안에 골조선)·기둥 위를 지나는 부분이 40% 이상인 것만"""
    from scipy.spatial import cKDTree
    from geom import to_segments, sample_points
    if not len(golf_segs):
        return cen
    gp = sample_points(golf_segs, step=100.0)
    tree = cKDTree(gp[:, :2])
    keep = []
    for p in cen:
        segs = to_segments([p])
        if not len(segs):
            continue
        sp = sample_points(segs, step=500.0)
        if not len(sp):
            keep.append(p); continue
        near = tree.query_ball_point(sp[:, :2], 450.0)
        ok = sum(1 for lst in near if len(lst) >= 2) / len(sp)
        if ok >= 0.4:
            keep.append(p)
    return keep


def open_marks(fid, texts, prims):
    """OPEN 문자 둘레의 X(대각선) + 같은 레이어 둘레 선"""
    outp = []
    lines = [p for p in prims if p["kind"] == "LINE"]
    for t in texts:
        R = max(3 * t.get("h", 0), 1500.0)
        xs = []
        for p in lines:
            ang = abs(math.degrees(math.atan2(p["y2"] - p["y1"], p["x2"] - p["x1"]))) % 180
            if not (15 <= ang <= 75 or 105 <= ang <= 165):
                continue
            # 점-선분 거리
            ax, ay, bx, by = p["x1"], p["y1"], p["x2"], p["y2"]
            L2 = (bx - ax) ** 2 + (by - ay) ** 2
            u = max(0, min(1, ((t["x"] - ax) * (bx - ax) + (t["y"] - ay) * (by - ay)) / L2)) if L2 else 0
            dd = math.hypot(ax + u * (bx - ax) - t["x"], ay + u * (by - ay) - t["y"])
            if dd <= R:
                xs.append(p)
        if not xs:
            continue
        bx0 = min(min(p["x1"], p["x2"]) for p in xs) - 200; bx1 = max(max(p["x1"], p["x2"]) for p in xs) + 200
        by0 = min(min(p["y1"], p["y2"]) for p in xs) - 200; by1 = max(max(p["y1"], p["y2"]) for p in xs) + 200
        same = [p for p in prims if p["layer"] == t["layer"] and all(bx0 <= q[0] <= bx1 and by0 <= q[1] <= by1 for q in rep_pts(p))]
        for p in xs + same:
            if p not in outp:
                outp.append(p)
    return outp


from geom import to_segments
STRUCT_ONLY = bool(CFG.get("중심선_구조만", False))
prims_by_floor = collections.defaultdict(list)
for p in msp:
    if p["kind"] in GEOM:
        fid = which(p)
        if fid is not None:
            prims_by_floor[fid].append(p)
for fid in sorted(floors):
    c = cand[fid]
    rects = find_rects(c["golf"])
    c["cols"] = rects
    if STRUCT_ONLY:
        c["cen"] = cen_structural(c["cen"], to_segments(c["golf"]), rects)
    for p in open_marks(fid, c["open_text"], prims_by_floor[fid]):  # OPEN 문자 둘레 X (레이어 무관) 추가
        if p not in c["open"]:
            c["open"].append(p)

# ---------- 5. 저장(호환 필드 FY/H 포함) ----------
order = sorted(floors)
meta = []
for fid in order:
    f = floors[fid]
    meta.append({"id": fid, "label": f["label"], "short": short_label(fid, f["label"]), "anchor": tuple(map(float, f["anchor"])), "bbox": [float(v) for v in f["bbox"]], "n": len(f["idx"])})
FY = {fid: float(floors[fid]["anchor"][1]) for fid in order}
ys = sorted(set(FY.values()))
H = float(np.median(np.diff(ys))) if len(ys) > 1 else 0.0
print(f"층 {len(order)}개 (제목 {len(titles)}개, 버린 덩어리 프리미티브 {dropped}):")
for m in meta:
    c = cand[m["id"]]
    print(f"  {m['short']:7} {m['label'][:28]:30} anchor=({m['anchor'][0]:.0f},{m['anchor'][1]:.0f}) 골조 {len(c['golf'])} 기둥 {len(c['cols'])} 중심선 {len(c['cen'])} OPEN {len(c['open'])}/{len(c['open_text'])}")
excl = collections.Counter()
for (fid, kind, ly), v in stat.items():
    if kind == "골조색-제외레이어":
        excl[ly] += v
if excl:
    print("  골조색이지만 제외 레이어:", dict(excl.most_common(10)))
pickle.dump({"floors": meta, "FY": FY, "H": H, "cand": cand, "cfg": CFG}, open(out, "wb"), protocol=5)
print("saved", out)
