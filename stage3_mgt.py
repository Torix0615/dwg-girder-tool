"""3단계: 2단계 결과를 MIDAS Gen 텍스트(MGT) 모델로 작성.
python stage3_mgt.py out/s1_cand.pkl out/s2_model.pkl out/s2_result.pkl out/model.mgt [--config config.json] [--report f]
규칙(명령문 3단계):
 1. MATERIAL: C27(1), C35(2)  — 기둥=C35, 거더·보·벽=C27 (가정)
 2. SECTION : 10 C1(기둥, 도면 최빈 기둥 치수), 100 G1(거더), 500 B1(보)
 3. THICKNESS: 200(내벽), 500(최외각 벽)
 4. STORY   : 도면(층)마다 5m, 건축물 하부층부터 위로. 도면 N 층의 기둥·벽은 N 층 바닥(z_N)~N+1 층 바닥(z_N+5m), 그 위 도면(N+1)의 거더·보는 z_N+5m 에.
 5. 거더→G1(BEAM), 기둥→C1(BEAM, 수직), 벽→WALL(두께 200, 최외각 500)
 6. 상위 층 기둥·벽 절점이 하위 층 절점과 100mm 이내로 어긋나면 하위 층 위치로 맞춤
 7. 벽 번호: 방향이 꺾이는 곳에서 바뀜. 최외각 1부터, 내부는 최외각 마지막 번호+100부터
 8. G1 양끝 중 기둥에 닿지 않는 끝(벽·거더 T접합)과 연속이 끝나는 끝은 PIN(My,Mz 해제, 값 0). 보(B1)는 양끝 PIN(가정)
단위 KN, MM. 최하층 바닥 절점 고정(111111).
"""
import sys, math, pickle, collections, time
import numpy as np
from shapely.geometry import LineString, Polygon, Point, MultiPolygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from cfg import pop_config_arg
import stage2_engine as E

CFG, argv = pop_config_arg(sys.argv[1:])
cand_p, model_p, result_p, out_p = argv[0:4]
report = argv[argv.index("--report") + 1] if "--report" in argv else None
STORY_H = float(CFG.get("MGT_층고", 5000))
SNAP = float(CFG.get("MGT_미세어긋남", 100))
T_IN, T_OUT = float(CFG.get("MGT_내벽두께", 200)), float(CFG.get("MGT_외벽두께", 500))
E_C27 = round(8500 * (27 + 4) ** (1 / 3) / 1000, 3)  # kN/mm² (KCI: Ec = 8500·(fck+Δf)^(1/3) MPa)
E_C35 = round(8500 * (35 + 4) ** (1 / 3) / 1000, 3)

C = pickle.load(open(cand_p, "rb")); cand = C["cand"]
M = pickle.load(open(model_p, "rb")); model = M["model"]
RES = pickle.load(open(result_p, "rb")); result, floors = RES["result"], RES["floors"]
t0 = time.time()
lines_log = []
def log(s):
    print(s, flush=True); lines_log.append(s)

order = [f["id"] for f in floors if f["id"] in model]  # 아래층부터(생성된 1층 바닥 등 모델 없는 층은 제외: 그 거더는 지지층 위에 놓임)
short = {f["id"]: f["short"] for f in floors}
anchor = {f["id"]: np.array(f["anchor"], dtype=float) for f in floors}
# 도면마다 자기 층 기준점으로 좌표를 맞춤(층을 같은 평면 위치에 겹쳐 쌓기): 좌표 - anchor + anchor[최하층]
base = anchor[order[0]]
def to_model(fid, xy):
    return np.asarray(xy, dtype=float) - anchor[fid] + base


# ---------------- 절점 ----------------
class Nodes:
    def __init__(self):
        self.pts = []; self.index = {}
    def key(self, x, y, z):
        return (round(x), round(y), round(z))
    def get(self, x, y, z):
        k = self.key(x, y, z)
        i = self.index.get(k)
        if i is None:
            i = len(self.pts) + 1; self.pts.append((x, y, z)); self.index[k] = i
        return i
    def find_near(self, x, y, z, r):
        """같은 z 에서 r 안의 기존 절점(가장 가까운) 번호"""
        best, bd = None, None
        for k, i in self.index.items():
            if k[2] == round(z):
                d = math.hypot(k[0] - x, k[1] - y)
                if d <= r and (bd is None or d < bd):
                    best, bd = i, d
        return best

nodes = Nodes()
elements = []   # dict(id, type, mat, pro, n, sub, wid)
releases = []   # (elem id, flag_i, flag_j)
story_levels = {}  # fid -> z (바닥)
for i, fid in enumerate(order):
    story_levels[fid] = STORY_H * i
TOP_Z = STORY_H * len(order)

# ---------------- 기둥(층별, 아래층 위치로 스냅) ----------------
col_xy_by_floor = {}
prev_cols = None
for fid in order:
    pts = []
    for c in model[fid]["cols"]:
        p = to_model(fid, (c["cx"], c["cy"]))
        if prev_cols is not None and len(prev_cols):
            d = np.hypot(prev_cols[:, 0] - p[0], prev_cols[:, 1] - p[1])
            j = int(np.argmin(d))
            if d[j] <= SNAP:
                p = prev_cols[j].copy()
        pts.append(p)
    col_xy_by_floor[fid] = np.array(pts) if pts else np.zeros((0, 2))
    prev_cols = col_xy_by_floor[fid]
# 기둥 단면 C1: 최빈 치수
sizes = collections.Counter()
for fid in order:
    for c in model[fid]["cols"]:
        sizes[(int(round(2 * c["hw"] / 50) * 50), int(round(2 * c["hh"] / 50) * 50))] += 1
C1 = sizes.most_common(1)[0][0] if sizes else (600, 600)
log(f"기둥 단면 C1 = {C1[0]}x{C1[1]} (최빈, 후보 {len(sizes)}종)")

eid = 0
col_nodes_by_floor = {}  # fid -> set of node ids at top z (거더 연결 판정)
for fid in order:
    z0 = story_levels[fid]; z1 = z0 + STORY_H
    tops = set(); bots = set()
    for p in col_xy_by_floor[fid]:
        a = nodes.get(p[0], p[1], z0); b = nodes.get(p[0], p[1], z1)
        eid += 1
        elements.append({"id": eid, "type": "BEAM", "mat": 2, "pro": 10, "n": (a, b), "kind": "col", "floor": fid})
        tops.add(b); bots.add(a)
    col_nodes_by_floor[fid] = {"top": tops, "bot": bots}

# ---------------- 벽(중심선·두께·최외각·번호) ----------------
def wall_centerlines(con, con_th):
    """짝 있는 벽 면 선분 → 중심선 (x1,y1,x2,y2,th). 짝 없는 선은 제외"""
    from scipy.spatial import cKDTree
    n = len(con)
    if n == 0:
        return []
    d = con[:, 2:] - con[:, :2]; L = np.hypot(d[:, 0], d[:, 1]); u = d / np.maximum(L, 1e-9)[:, None]
    mid = (con[:, :2] + con[:, 2:]) / 2; t = cKDTree(mid)
    out = []; used = set()
    for i in range(n):
        th = con_th[i]
        if not np.isfinite(th) or L[i] < 300 or i in used:
            continue
        best = None
        for j in t.query_ball_point(mid[i], L[i] / 2 + th + 50):
            if j == i or j in used or abs(np.dot(u[i], u[j])) < 0.9994 or L[j] < 300:
                continue
            w = mid[j] - mid[i]; perp = abs(w[0] * u[i][1] - w[1] * u[i][0])
            if abs(perp - th) > 20:
                continue
            pj = [np.dot(con[j, :2] - con[i, :2], u[i]), np.dot(con[j, 2:] - con[i, :2], u[i])]
            lo = max(0.0, min(pj)); hi = min(L[i], max(pj))
            if hi - lo >= 0.5 * min(L[i], L[j]) and (best is None or (hi - lo) > best[0]):
                best = (hi - lo, j, lo, hi, w)
        if best is None:
            continue
        _, j, lo, hi, w = best
        used.add(i); used.add(j)
        nrm = np.array([-u[i][1], u[i][0]]); side = np.sign(np.dot(w, nrm)) or 1.0
        off = nrm * (th / 2) * side
        a = con[i, :2] + u[i] * lo + off; b = con[i, :2] + u[i] * hi + off
        out.append((a[0], a[1], b[0], b[1], th))
    return out


def footprint(con, cols):
    """층 외곽(최외각 판정용): 벽·기둥을 1m 버퍼로 합쳐 구멍을 메운 폴리곤"""
    geoms = [LineString([(s[0], s[1]), (s[2], s[3])]) for s in con] + [Polygon([tuple(v) for v in c["poly"]]) for c in cols]
    if not geoms:
        return None
    u = unary_union([g.buffer(1000, join_style=2) for g in geoms])
    polys = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
    polys = [Polygon(p.exterior) for p in polys if p.area > 50e6]  # 구멍 제거
    return unary_union(polys).buffer(-900, join_style=2) if polys else None


def chains(segs, ang_tol=2.0, gap=50.0):
    """선분들을 끝점 연결·같은 방향으로 이어 체인(벽 번호 단위)으로 묶음. 방향이 바뀌면 새 체인"""
    segs = [np.array(s[:4], dtype=float) for s in segs]
    used = [False] * len(segs); out = []
    def ang(s):
        return math.degrees(math.atan2(s[3] - s[1], s[2] - s[0])) % 180
    for i, s in enumerate(segs):
        if used[i]:
            continue
        used[i] = True; chain = [i]
        # 양쪽으로 확장
        for end in (1, 0):
            cur = i; pt = segs[cur][2:] if end else segs[cur][:2]
            while True:
                found = None
                for j, t in enumerate(segs):
                    if used[j] or abs(ang(segs[cur]) - ang(t)) > ang_tol and abs(abs(ang(segs[cur]) - ang(t)) - 180) > ang_tol:
                        continue
                    if np.hypot(*(t[:2] - pt)) <= gap:
                        found, pt = j, t[2:]; break
                    if np.hypot(*(t[2:] - pt)) <= gap:
                        found, pt = j, t[:2]; break
                if found is None:
                    break
                used[found] = True; chain.append(found); cur = found
        out.append([segs[k] for k in chain])
    return out


wall_count = {"ext": 0, "int": 0}
wall_id_counter = 0
for fid in order:
    m = model[fid]
    z0 = story_levels[fid]; z1 = z0 + STORY_H
    wl = wall_centerlines(m["con"], m["con_th"])
    fp = footprint(m["con"], m["cols"])
    ext, inner = [], []
    for s in wl:
        a = np.array(s[:2]); b = np.array(s[2:4]); th = s[4]
        d = b - a; L = np.hypot(*d)
        if L < 300 or fp is None:
            inner.append(s); continue
        nrm = np.array([-d[1], d[0]]) / L
        mid = (a + b) / 2
        outside = any(not fp.contains(Point(*(mid + nrm * sgn * (th / 2 + 400)))) for sgn in (1, -1))
        (ext if outside else inner).append(s)
    ext_chains = chains(ext); int_chains = chains(inner)
    n_ext = len(ext_chains)
    wid = 0
    for group, start in ((ext_chains, 1), (int_chains, n_ext + 100)):
        wid = start
        for ch in group:
            for s in ch:
                a = to_model(fid, s[:2]); b = to_model(fid, s[2:4])
                # 절점 스냅: 기둥 절점 100mm 안이면 그 위치
                na0 = nodes.find_near(a[0], a[1], z0, SNAP); nb0 = nodes.find_near(b[0], b[1], z0, SNAP)
                n1 = na0 or nodes.get(a[0], a[1], z0); n2 = nb0 or nodes.get(b[0], b[1], z0)
                pa = nodes.pts[n1 - 1]; pb = nodes.pts[n2 - 1]
                n3 = nodes.get(pb[0], pb[1], z1); n4 = nodes.get(pa[0], pa[1], z1)
                if n1 == n2:
                    continue
                eid += 1
                thk = 2 if group is ext_chains else 1
                elements.append({"id": eid, "type": "WALL", "mat": 1, "pro": thk, "n": (n1, n2, n3, n4), "kind": "wall", "wid": wid, "floor": fid})
            wid += 1
    wall_count["ext"] += sum(len(c) for c in ext_chains); wall_count["int"] += sum(len(c) for c in int_chains)
    log(f"{short[fid]:7}: 기둥 {len(col_xy_by_floor[fid])} 벽요소 외벽 {sum(len(c) for c in ext_chains)}(번호 1~{n_ext}) 내벽 {sum(len(c) for c in int_chains)}(번호 {n_ext+100}~)")

# ---------------- 거더·보(도면 N 의 거더는 지지층 k 의 기둥 위, z = z_k + 층고) ----------------
def split_at_points(segs, pts, tol=10.0):
    """선분 내부에 다른 끝점이 놓이면 거기서 나눔(T 접합 연결)"""
    out = []
    P = np.array(pts) if len(pts) else np.zeros((0, 2))
    for s in segs:
        a = np.array(s[:2]); b = np.array(s[2:4]); d = b - a; L = np.hypot(*d)
        if L < 1:
            continue
        u = d / L
        ts = [0.0, 1.0]
        if len(P):
            rel = P - a; along = rel @ u; perp = np.abs(rel[:, 0] * u[1] - rel[:, 1] * u[0])
            for t_, pp in zip(along, perp):
                if 20 < t_ < L - 20 and pp <= tol:
                    ts.append(t_ / L)
        ts = sorted(set(round(t_, 6) for t_ in ts))
        for t1, t2 in zip(ts[:-1], ts[1:]):
            out.append((*(a + d * t1), *(a + d * t2), s[4] if len(s) > 4 else None))
    return out


n_g = n_b = n_pin = 0
for N, R in result.items():
    k = R["support"]
    if k not in story_levels:
        continue
    z = story_levels[k] + STORY_H
    G = [(*E.to_segs([g])[0], g.get("kb", "")) for g in R["girders"]] if R["girders"] else []
    B = [(*E.to_segs([b])[0], "beam") for b in R["beams"]] if R["beams"] else []
    # 지지층 좌표 → 모델 좌표
    def tm(s):
        a = to_model(k, s[:2]); b = to_model(k, s[2:4]); return (a[0], a[1], b[0], b[1], s[4])
    G = [tm(s) for s in G]; B = [tm(s) for s in B]
    ends = [(s[0], s[1]) for s in G] + [(s[2], s[3]) for s in G] + [(s[0], s[1]) for s in B] + [(s[2], s[3]) for s in B]
    G = split_at_points(G, ends); B = split_at_points(B, ends)
    col_top = col_nodes_by_floor[k]["top"]
    # 연속성: 각 끝점에서 같은 방향으로 이어지는 거더가 있는지
    gl = [np.array(s[:4]) for s in G]
    def continues(pt, dirv, exclude):
        for j, s in enumerate(gl):
            if j == exclude:
                continue
            for e0, e1 in ((s[:2], s[2:]), (s[2:], s[:2])):
                if np.hypot(*(e0 - pt)) <= SNAP:
                    v = e1 - e0; v = v / (np.hypot(*v) or 1)
                    if np.dot(v, dirv) > 0.985:  # 같은 방향(±10°)
                        return True
        return False
    for i, s in enumerate(G):
        n1 = nodes.find_near(s[0], s[1], z, SNAP) or nodes.get(s[0], s[1], z)
        n2 = nodes.find_near(s[2], s[3], z, SNAP) or nodes.get(s[2], s[3], z)
        if n1 == n2:
            continue
        eid += 1; n_g += 1
        elements.append({"id": eid, "type": "BEAM", "mat": 1, "pro": 100, "n": (n1, n2), "kind": "girder", "floor": N})
        a = np.array(s[:2]); b = np.array(s[2:4]); dv = (b - a) / (np.hypot(*(b - a)) or 1)
        pin_i = (n1 not in col_top) or not continues(a, -dv, i)
        pin_j = (n2 not in col_top) or not continues(b, dv, i)
        if pin_i or pin_j:
            releases.append((eid, pin_i, pin_j)); n_pin += 1
    for s in B:
        n1 = nodes.find_near(s[0], s[1], z, SNAP) or nodes.get(s[0], s[1], z)
        n2 = nodes.find_near(s[2], s[3], z, SNAP) or nodes.get(s[2], s[3], z)
        if n1 == n2:
            continue
        eid += 1; n_b += 1
        elements.append({"id": eid, "type": "BEAM", "mat": 1, "pro": 500, "n": (n1, n2), "kind": "beam", "floor": N})
        releases.append((eid, True, True))
# 같은 절점 조합의 중복 요소 제거(거더 분할·벽 겹침) 후 번호 다시 매김
seen = set(); uniq = []
for e in elements:
    key = (e["type"], tuple(sorted(e["n"])))
    if key in seen:
        continue
    seen.add(key); uniq.append(e)
remap = {}
for i, e in enumerate(uniq, 1):
    remap[e["id"]] = i; e["id"] = i
elements = uniq
releases = [(remap[i], pi, pj) for i, pi, pj in releases if i in remap]
log(f"거더 {n_g}개(PIN {n_pin}개) 보 {n_b}개, 절점 {len(nodes.pts)}개, 요소 {len(elements)}개(중복 제거 후)")

# ---------------- MGT 쓰기 ----------------
def fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def id_ranges(ids):
    """[1,2,3,7,9,10] → '1to3 7 9 10' (MGT 목록 표기)"""
    ids = sorted(set(int(i) for i in ids)); out = []; i = 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        out.append(f"{ids[i]}to{ids[j]}" if j > i + 1 else (f"{ids[i]} {ids[j]}" if j == i + 1 else str(ids[i])))
        i = j + 1
    return " ".join(out)


def cont_lines(first, body, width=70):
    """MGT 줄 이어쓰기: 줄 끝 ' \' 로 다음 줄에 계속(내보내기 파일과 같은 형식)"""
    toks = body.split(); lines = []; cur = []
    for t in toks:
        if sum(len(x) + 1 for x in cur) + len(t) > width and cur:
            lines.append(" ".join(cur)); cur = []
        cur.append(t)
    if cur:
        lines.append(" ".join(cur))
    if not lines:
        return [first]
    out = [first + lines[0]]
    for ln in lines[1:]:
        out[-1] += " \\"
        out.append("        " + ln)
    return out

L = []
L.append(";---------------------------------------------------------------------------")
L.append(";  midas Gen Text(MGT) File. 골조·거더·보 생성기 3단계 자동 작성")
L.append(f";  Date : {time.strftime('%Y/%m/%d')}")
L.append(";---------------------------------------------------------------------------")
L.append("")
L.append("*VERSION"); L.append("   9.5.5"); L.append("")
L.append("*UNIT    ; Unit System"); L.append("; FORCE, LENGTH, HEAT, TEMPER"); L.append("   KN   , MM, KCAL, C"); L.append("")
L.append("*STRUCTYPE    ; Structure Type")
L.append("; iSTYP, iMASS, iSMAS, bMASSOFFSET, bSELFWEIGHT, GRAV, TEMPER, bALIGNBEAM, bALIGNSLAB, bROTRIGID")
L.append("     0, 1, 1, NO, YES, 9806, 0, YES, YES, NO"); L.append("")
L.append("*NODE    ; Nodes"); L.append("; iNO, X, Y, Z")
for i, (x, y, z) in enumerate(nodes.pts, 1):
    L.append(f"   {i}, {fmt(float(x))}, {fmt(float(y))}, {fmt(float(z))}")
L.append("")
L.append("*ELEMENT    ; Elements")
L.append("; iEL, TYPE, iMAT, iPRO, iN1, iN2, ANGLE, iSUB,                     ; Frame  Element")
L.append("; iEL, TYPE, iMAT, iPRO, iN1, iN2, iN3, iN4, iSUB, iWID , LCAXIS    ; Planar Element")
for e in elements:
    if e["type"] == "BEAM":
        L.append(f"   {e['id']}, BEAM  , {e['mat']}, {e['pro']}, {e['n'][0]}, {e['n'][1]}, 0, 0")
    else:
        L.append(f"   {e['id']}, WALL  , {e['mat']}, {e['pro']}, {e['n'][0]}, {e['n'][1]}, {e['n'][2]}, {e['n'][3]}, 2, {e['wid']}, 0, 0")
L.append("")
L.append("*MATERIAL    ; Material")
L.append("; iMAT, TYPE, MNAME, SPHEAT, HEATCO, PLAST, TUNIT, bMASS, DAMPRATIO, [DATA1]           ; STEEL, CONC, ALUMINUM, USER")
L.append("; [DATA1] : 1, STANDARD, CODE/PRODUCT, DB, USEELAST, ELAST")
L.append(f"    1, CONC , C27, 0, 0, , C, NO, 0.05, 1, KS01(RC), , C27, NO, {E_C27}")
L.append(f"    2, CONC , C35, 0, 0, , C, NO, 0.05, 1, KS01(RC), , C35, NO, {E_C35}")
L.append("")
L.append("*SECTION    ; Section")
L.append("; iSEC, TYPE, SNAME, [OFFSET], bSD, bWE, SHAPE, [DATA1], [DATA2]                    ; 1st line - DB/USER")
L.append(f"   10, DBUSER    , C1, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB , 2, {C1[0]}, {C1[1]}, 0, 0, 0, 0, 0, 0, 0, 0")
L.append(f"  100, DBUSER    , G1, CT, 0, 0, 0, 0, 0, 0, YES, NO, SB , 2, {int(CFG.get('거더폭_Y', 500))}, {int(CFG.get('MGT_거더춤', 700))}, 0, 0, 0, 0, 0, 0, 0, 0")
L.append(f"  500, DBUSER    , B1, CT, 0, 0, 0, 0, 0, 0, YES, NO, SB , 2, {int(CFG.get('보폭', 400))}, {int(CFG.get('MGT_보춤', 600))}, 0, 0, 0, 0, 0, 0, 0, 0")
L.append("")
L.append("*THICKNESS    ; Thickness")
L.append("; iTHK, TYPE, NAME, bSAME, THIK-IN, THIK-OUT, bOFFSET, OFFTYPE, VALUE ; TYPE=VALUE")
L.append(f"    1, VALUE, W{int(T_IN)}, YES, {int(T_IN)}, 0,  NO, 0, 0")
L.append(f"    2, VALUE, W{int(T_OUT)}, YES, {int(T_OUT)}, 0,  NO, 0, 0")
L.append("")
L.append("*STORY    ; Story")
L.append(";  NAME=NAME, LEVEL, bFLDIAP, WINDWX, WINDWY, WINDCX, WINDCY, ECCX, ECCY, IECCX, IECCY, TAFX, TAFY, WTAFX, WTAFY, AreaPosNum ; line 1")
for fid in order:
    L.append(f"   NAME={short[fid]}, {fmt(float(story_levels[fid]))}, YES, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0")
L.append(f"   NAME=ROOF, {fmt(float(TOP_Z))}, YES, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0")
L.append("")
L.append("*CONSTRAINT    ; Supports")
L.append("; NODE_LIST, CONST(Dx,Dy,Dz,Rx,Ry,Rz), GROUP")
base_nodes = [i for i, (x, y, z) in enumerate(nodes.pts, 1) if round(z) == 0]
bl = cont_lines("   ", id_ranges(base_nodes)); bl[-1] += ", 111111, "; L += bl
L.append("")
if releases:
    L.append("*FRAME-RLS    ; Beam End Release")
    L.append("; ELEM_LIST, FLAG-i, Fxi, Fyi, Fzi, Mxi, Myi, Mzi, FLAG-j, Fxj, Fyj, Fzj, Mxj, Myj, Mzj, GROUP")
    # Quick Reference 표기대로 2줄: 1줄 = 요소, i단 플래그(Fx Fy Fz Mx My Mz, 1=해제)·상대강성(0=완전 해제) / 2줄 = j단, 그룹
    for e_id, pi, pj in releases:
        fi = "000011" if pi else "000000"; fj = "000011" if pj else "000000"
        L.append(f"   {e_id}, {fi}, 0, 0, 0, 0, 0, 0")
        L.append(f"        {fj}, 0, 0, 0, 0, 0, 0, ")
    L.append("")
L.append("*GROUP    ; Group"); L.append("; NAME, NODE_LIST, ELEM_LIST, PLANE_TYPE")
for kind, name in (("col", "C1_COLUMN"), ("girder", "G1_GIRDER"), ("beam", "B1_BEAM"), ("wall", "WALL")):
    ids = [e["id"] for e in elements if e["kind"] == kind]
    if ids:
        gl = cont_lines(f"   {name}, , ", id_ranges(ids)); gl[-1] += ", 0"; L += gl
L.append("")
L.append("*ENDDATA")
open(out_p, "w", encoding="utf-8", newline="\r\n").write("\n".join(L) + "\n")
log(f"saved {out_p} ({len(L)} 줄, {time.time()-t0:.0f}s)")
if report:
    open(report, "w", encoding="utf-8").write("\n".join(lines_log))
