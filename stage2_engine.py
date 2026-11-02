"""2단계 엔진: 지지층(k) 구조(기둥·벽)에서 거더·보 중심선을 생성.
규칙
 1. 모든 선은 기둥 중심 기준(중심→중심).
 2. 기둥의 4방향(기둥 사각형 축 ±ux, ±uy)으로 가장 가까운 기둥(각도 ±ANG° 안)을 찾아 GIRDER.
    기둥 1면당 거더 1개(피드백 ce4a4d): 축 어긋남이 작은 쌍부터 확정하고, 이미 거더가 붙은 면은 건너뜀.
 3. 인접 기둥끼리만: 방향별 최근접 1개, 사이에 벽이 가로막으면 벽 면까지만.
    기둥이 없으면 벽 면까지(Lmax 안), 벽도 없으면 기존 거더에 T 접합(벽이 먼저면 벽).
 4/5. 거더·벽으로 둘러싸인 베이(폴리곤)마다: Y방향 변 > SPLIT 이면 X방향(가까운 축) 보를 베이 중앙에,
      아니고 X방향 변 > SPLIT 이면 Y방향 보.
    MAIN/SUB(피드백 ce4a4d): 층에서 보가 더 많이 뻗는 방향(길이 합)이 MAIN, 직각이 SUB. 보는 되도록 MAIN 방향.
    보끼리 만나면 SUB 방향 보를 MAIN 보에서 끊는다: SUB 보는 MAIN 보를 가로지르지 못함.
    SUB_CROSS="제거"(기본) = MAIN 보와 교차하는 SUB 보를 없앰(참조 수작업본 6층 모두 X·Y 보 교차 0쌍, MAIN 한 방향 보).
    SUB_CROSS="분할" = SUB 보를 MAIN 보 교차점에서 나눠 조각을 남김(양방향 격자).
 6. 동(아파트) 폴리곤 안의 기둥은 주차장 거더 생성에서 제외(별도 파일 처리).
 7. 간섭 금지(피드백 c1d6e4): 거더·보가 서로 겹치거나(평행·OVERLAP_PERP 안) 교차하지 않게.
    우선순위 = 기둥-기둥 거더 > 기둥-벽 거더 > T접합 거더 > MAIN 보 > SUB 보, 같으면 긴 것.
    겹침은 우선 1개만 남기고(나머지는 겹친 구간을 잘라냄), 교차는 낮은 쪽을 교차점에서 분할.
반환: girders=[{a,b,ka,kb,i,j,rank}], beams=[{a,b,xish,main,rank}]
"""
import math
import numpy as np
from shapely.geometry import LineString, Polygon, MultiLineString
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree
import shapely


class Params:
    LMAX = 14000.0      # 거더 최대 탐색 길이
    ANG = 8.0           # 축 대비 허용 각도(도)
    PERP_MIN = 700.0    # 가까운 기둥의 횡 오차 허용
    WALL_MIN_LEN = 200.0
    WALL_CROSS_DEG = 35.0  # 벽이 광선과 이루는 최소 각(평행 벽 무시)
    MAKE_BEAMS = True   # False 면 보를 만들지 않음(거더만, 설정 보_생성)
    SPLIT = 6000.0      # 보 분할 기준 거더 길이(이보다 긴 거더 옆 베이에 평행 보)
    D_MIN = 3000.0      # 베이 폭(반대편 경계까지) 최소
    D_TWO = 8700.0      # 베이 폭이 이 이상이면 보 2개(3등분)
    D_THREE = 14000.0   # 보 3개(4등분)
    BEAM_LMAX = 14000.0
    T_JUNCTION = True
    WALL_GIRDER = True
    MIN_GIRDER = 300.0
    BAY_MIN_AREA = 8e6     # 베이 최소 면적(8 m²)
    BAY_MAX_AREA = 400e6
    BAY_RECT_RATIO = 0.55  # 면적/최소외접사각형 면적
    EXCLUDE_DONG = True
    WALL_TH_MIN = 0.0          # 거더용 벽 최소 두께(0=모든 CON 선)
    BEAM_WALL_TH = 250.0       # 보 경계로 쓸 구조벽 최소 두께
    BEAM_WALL_SINGLE = 1e12    # 보 경계로 쓸 짝 없는 단일선 최소 길이
    WALL_SINGLE_MINLEN = 0.0   # 거더용: 짝 없는 단일선을 벽으로 볼 최소 길이(0=모두)
    SPLIT3 = 0.0           # >0 이면 이 길이 넘는 변은 3등분(0=사용 안 함)
    FACE_ONE = True        # 기둥 1면당 거더 1개
    SUB_CROSS = "제거"      # 보끼리 교차: "제거"=MAIN 보를 가로지르는 SUB 보 삭제(기본, 참조 기준) / "분할"=교차점에서 나눠 조각 유지
    OVERLAP_PERP = 100.0   # 간섭(겹침) 판정: 평행한 두 선 사이 거리(mm)
    MIN_PIECE = 300.0      # 분할·트림 뒤 남길 최소 길이(mm)
    MAIN_TIE = 0.10        # MAIN/SUB 판정: 두 축 보 길이 합 차이가 이 비율 안이면 동률 → X


RANK = {"col": 0, "wall": 1, "girder": 2}   # 거더 끝 종류별 우선순위(낮을수록 우선)


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def seg_len(it):
    return float(np.hypot(it["b"][0] - it["a"][0], it["b"][1] - it["a"][1]))


def col_extent(col, d):
    return max(abs(np.dot(v - np.array([col["cx"], col["cy"]]), d)) for v in col["poly"])


def seg_dir(s):
    return unit(np.array([s[2] - s[0], s[3] - s[1]]))


def col_faces(c):
    return [unit(np.asarray(v, dtype=float)) for v in (c["ux"], -np.asarray(c["ux"]), c["uy"], -np.asarray(c["uy"]))]


def face_index(c, d):
    """방향 d 가 기둥 c 의 어느 면인지(0:+ux 1:-ux 2:+uy 3:-uy)"""
    return int(np.argmax([float(np.dot(f, d)) for f in col_faces(c)]))


def build_wall_tree(con, P, con_th=None):
    L = np.hypot(con[:, 2] - con[:, 0], con[:, 3] - con[:, 1])
    sel = L >= P.WALL_MIN_LEN
    if con_th is not None:
        th = np.asarray(con_th)
        sel &= ((th >= P.WALL_TH_MIN) & (th <= 700)) | (np.isnan(th) & (L >= P.WALL_SINGLE_MINLEN))
    con = con[sel]
    geoms = [LineString([(s[0], s[1]), (s[2], s[3])]) for s in con]
    return con, geoms, STRtree(geoms)


def ray_hit(p0, d, lmax, segs, geoms, tree, min_cross_deg, exclude=None):
    """p0 에서 d 방향 광선과 선분들의 최근접 교차점 (거리, 점, index)"""
    p1 = p0 + d * lmax
    ray = LineString([tuple(p0), tuple(p1)])
    best = None
    sin_min = math.sin(math.radians(min_cross_deg))
    for idx in tree.query(ray):
        if exclude is not None and idx in exclude:
            continue
        s = segs[idx]
        sd = seg_dir(s)
        if abs(sd[0] * d[1] - sd[1] * d[0]) < sin_min:
            continue
        inter = ray.intersection(geoms[idx])
        if inter.is_empty:
            continue
        pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
        for q in pts:
            if q.geom_type != "Point":
                continue
            t = np.dot(np.array([q.x, q.y]) - p0, d)
            if t <= 0:
                continue
            if best is None or t < best[0]:
                best = (t, np.array([q.x, q.y]), idx)
    return best


def generate(cols, con, P=Params(), dong=None, con_th=None):
    dong = dong or []
    if P.EXCLUDE_DONG and dong:
        dpolys = [Polygon(g) if not isinstance(g, Polygon) else g for g in dong]
        du = unary_union(dpolys)
        cols = [c for c in cols if not du.contains(shapely.points(c["cx"], c["cy"]))]
    if not cols:
        return [], []
    centers = np.array([[c["cx"], c["cy"]] for c in cols])
    walls, wgeoms, wtree = build_wall_tree(con, P, con_th)
    girders = []
    pending = []
    pair_set = set()
    faces = {}       # (기둥, 면) -> 거더 index : 1면 1거더
    wall_hit = {}    # (기둥, 면) -> 벽 광선 결과
    tan_ang = math.tan(math.radians(P.ANG))
    # 1) 기둥-기둥 후보: 면마다 최근접 기둥. 축 어긋남(횡오차/거리)이 작은 쌍부터 확정
    cand_pairs = []
    for i, c in enumerate(cols):
        ci = centers[i]
        for fi, d in enumerate(col_faces(c)):
            v = centers - ci
            along = v @ d
            perp = np.abs(v[:, 0] * d[1] - v[:, 1] * d[0])
            ok = (along > 100) & (along <= P.LMAX) & (perp <= np.maximum(P.PERP_MIN, along * tan_ang))
            ok[i] = False
            start = ci + d * (col_extent(c, d) + 5)
            wall_hit[(i, fi)] = ray_hit(start, d, P.LMAX, walls, wgeoms, wtree, P.WALL_CROSS_DEG) if P.WALL_GIRDER else None
            if ok.any():
                cand = np.where(ok)[0]
                j = int(cand[np.argmin(along[cand])])
                cand_pairs.append((float(perp[j] / max(along[j], 1.0)), float(along[j]), i, fi, j, d, start))
    cand_pairs.sort(key=lambda t: (round(t[0], 4), t[1]))
    for q, aj, i, fi, j, d, start in cand_pairs:
        ci = centers[i]
        fj = face_index(cols[j], -d)
        key = (min(i, j), max(i, j))
        if key in pair_set:
            continue
        if P.FACE_ONE and ((i, fi) in faces or (j, fj) in faces):
            continue  # 그 면에는 이미 거더가 있음(1면 1거더) → 이 면은 벽/T접합 단계로
        wh = wall_hit[(i, fi)]
        ext_j = col_extent(cols[j], d)
        blocked = wh is not None and (wh[0] + np.dot(start - ci, d)) < aj - ext_j - 50
        if blocked:
            continue
        pair_set.add(key)
        faces[(i, fi)] = faces[(j, fj)] = len(girders)
        girders.append({"a": ci, "b": centers[j], "ka": "col", "kb": "col", "i": i, "j": j, "rank": RANK["col"]})
    # 2) 거더 없는 면: 벽 면까지, 벽도 없으면 T 접합 대기
    for i, c in enumerate(cols):
        ci = centers[i]
        for fi, d in enumerate(col_faces(c)):
            if (i, fi) in faces:
                continue
            wh = wall_hit[(i, fi)]
            if wh is not None:
                hp = wh[1]
                if np.linalg.norm(hp - ci) >= P.MIN_GIRDER:
                    faces[(i, fi)] = len(girders)
                    girders.append({"a": ci, "b": hp, "ka": "col", "kb": "wall", "i": i, "j": None, "rank": RANK["wall"]})
                continue
            pending.append((i, d))
    # T 접합(벽이 더 가까우면 벽)
    if P.T_JUNCTION and girders:
        gsegs = to_segs(girders)
        ggeoms = [LineString([(s[0], s[1]), (s[2], s[3])]) for s in gsegs]
        gtree = STRtree(ggeoms)
        for i, d in pending:
            c = cols[i]; ci = centers[i]
            start = ci + d * (col_extent(c, d) + 5)
            exclude = {gi for gi, g in enumerate(girders) if g["i"] == i or g["j"] == i}
            gh = ray_hit(start, d, P.LMAX, gsegs, ggeoms, gtree, 45.0, exclude=exclude)
            if gh is None:
                continue
            wh = ray_hit(start, d, gh[0], walls, wgeoms, wtree, P.WALL_CROSS_DEG)
            if wh is not None:
                continue  # 1차에서 못 찾은 벽이 거더보다 가까우면 생략(이미 벽 검색은 LMAX 로 했음)
            if np.linalg.norm(gh[1] - ci) >= P.MIN_GIRDER:
                girders.append({"a": ci, "b": gh[1], "ka": "col", "kb": "girder", "i": i, "j": None, "rank": RANK["girder"]})
    girders = resolve(girders, P)  # 거더끼리 간섭(겹침·교차) 정리
    # 보 계산은 구조벽(두께 ≥ BEAM_WALL_TH)만 경계로 사용
    if con_th is not None:
        th = np.asarray(con_th)
        Lc = np.hypot(con[:, 2] - con[:, 0], con[:, 3] - con[:, 1])
        walls_b = con[(Lc >= P.WALL_MIN_LEN) & (((th >= P.BEAM_WALL_TH) & (th <= 700)) | (np.isnan(th) & (Lc >= P.BEAM_WALL_SINGLE)))]
    else:
        walls_b = walls
    beams = make_beams(girders, walls_b, P, cols) if girders and P.MAKE_BEAMS else []
    if beams:
        beams = [b for b in resolve(girders + beams, P) if "xish" in b]  # 보는 거더·보와 간섭 없게(거더는 이미 확정)
    return girders, beams


def make_beams(girders, walls, P, cols=None):
    """띠(strip) 방식: 각 거더의 양쪽으로 수직 광선을 쏴 반대편 경계(거더/벽/기둥)까지 거리 D 를 잰다.
    D 가 일정하고 > SPLIT 이면 거더와 평행한 보를 D/2 에 둔다. MAIN 방향(보 길이 합이 큰 축) 보 우선."""
    gsegs = to_segs(girders)
    ggeoms = [LineString([(s[0], s[1]), (s[2], s[3])]) for s in gsegs]
    gtree = STRtree(ggeoms)
    wgeoms = [LineString([(s[0], s[1]), (s[2], s[3])]) for s in walls]
    wtree = STRtree(wgeoms)
    col_polys = [Polygon([tuple(v) for v in c["poly"]]) for c in (cols or [])]
    col_tree = STRtree(col_polys) if col_polys else None

    def hit_any(p0, d, lmax, exclude_g=()):
        best = None
        h = ray_hit(p0, d, lmax, gsegs, ggeoms, gtree, 45.0, exclude=set(exclude_g))
        if h is not None:
            best = (h[0], h[1])
        h = ray_hit(p0, d, lmax, walls, wgeoms, wtree, 45.0)
        if h is not None and (best is None or h[0] < best[0]):
            best = (h[0], h[1])
        if col_tree is not None:
            ray = LineString([tuple(p0), tuple(p0 + d * lmax)])
            for idx in col_tree.query(ray):
                inter = ray.intersection(col_polys[idx].exterior)
                if inter.is_empty:
                    continue
                pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
                for q in pts:
                    if q.geom_type != "Point":
                        continue
                    t = np.dot(np.array([q.x, q.y]) - p0, d)
                    if t > 1 and (best is None or t < best[0]):
                        best = (t, np.array([q.x, q.y]))
        return best

    raw = []
    TS = (0.12, 0.3, 0.5, 0.7, 0.88)
    for gi, g in enumerate(girders):
        s = gsegs[gi]
        L = math.hypot(s[2] - s[0], s[3] - s[1])
        if L <= P.SPLIT:
            continue
        d = seg_dir(s)
        n = np.array([-d[1], d[0]])
        a = s[:2]
        ang = abs(math.degrees(math.atan2(d[1], d[0]))) % 180
        xish = ang < 45 or ang > 135
        for sgn in (1, -1):
            nn = n * sgn
            ds = []
            for t in TS:
                p = a + d * (L * t)
                h = hit_any(p + nn * 2.0, nn, P.BEAM_LMAX, exclude_g=(gi,))
                ds.append(h[0] + 2.0 if h is not None else np.inf)
            ds = np.array(ds)
            fin = ds[np.isfinite(ds)]
            if len(fin) < 3:
                continue
            D = float(np.median(fin))
            if D < P.D_MIN or D > P.BEAM_LMAX:
                continue
            okm = np.isfinite(ds) & (np.abs(ds - D) <= max(0.12 * D, 300))
            if okm.sum() < 3:
                continue
            idx = np.where(okm)[0]
            t_lo = TS[idx[0]] - 0.12 if idx[0] > 0 else 0.0
            t_hi = TS[idx[-1]] + 0.12 if idx[-1] < len(TS) - 1 else 1.0
            t_lo = max(t_lo, 0.0); t_hi = min(t_hi, 1.0)
            if (t_hi - t_lo) * L < P.MIN_GIRDER:
                continue
            nb = 1 if D < P.D_TWO else (2 if D < P.D_THREE else 3)
            for q in range(1, nb + 1):
                off = a + nn * (D * q / (nb + 1))
                p_lo = off + d * (L * t_lo); p_hi = off + d * (L * t_hi)
                mid = (p_lo + p_hi) / 2
                half = np.linalg.norm(p_hi - p_lo) / 2
                ends = []
                for sg in (1, -1):
                    h = hit_any(mid, d * sg, half + 1500.0)
                    ends.append(mid + d * sg * min(h[0], half + 1500.0) if h is not None else mid + d * sg * half)
                raw.append({"a": ends[1], "b": ends[0], "xish": xish, "src": gi})
    if not raw:
        return []
    # MAIN 방향 = 보 길이 합이 큰 축(X 또는 Y). MAIN 보 rank 3, SUB 보 rank 4(교차 시 SUB 가 MAIN 에서 나뉨)
    lx = sum(seg_len(b) for b in raw if b["xish"]); ly = sum(seg_len(b) for b in raw if not b["xish"])
    # 두 축 길이 합이 MAIN_TIE(10%) 안이면 동률 → X(종전 X 우선, 1차 수작업 참조 X 85~90%). 같은 도면의 DXF/DWG 판에서 MAIN 이 갈리는 것 방지
    main_x = True if abs(lx - ly) <= P.MAIN_TIE * max(lx, ly, 1.0) else lx >= ly
    for b in raw:
        b["main"] = (b["xish"] == main_x)
        b["rank"] = 3 if b["main"] else 4
    if P.SUB_CROSS == "제거":
        mb = [LineString([tuple(b["a"]), tuple(b["b"])]) for b in raw if b["main"]]
        mt = STRtree(mb)
        keep = []
        for b in raw:
            if b["main"]:
                keep.append(b); continue
            ls = LineString([tuple(b["a"]), tuple(b["b"])])
            if not any(ls.crosses(mb[idx]) for idx in mt.query(ls)):
                keep.append(b)
    else:
        keep = raw
    # 같은 베이 양쪽 거더에서 나온 보(비스듬한 베이면 서로 몇 도 어긋남)는 하나로 합침
    return merge_collinear([b for b in keep if b["main"]], tol_perp=500.0, tol_ang=6.0) + merge_collinear([b for b in keep if not b["main"]], tol_perp=500.0, tol_ang=6.0)


def merge_collinear(beams, tol_perp=80.0, tol_ang=1.5):
    """평행·겹침 보를 하나로 합침"""
    out = []
    used = [False] * len(beams)
    for i, b in enumerate(beams):
        if used[i]:
            continue
        a, c = np.array(b["a"]), np.array(b["b"])
        d = unit(c - a)
        t0, t1 = 0.0, float(np.dot(c - a, d))
        for j in range(i + 1, len(beams)):
            if used[j]:
                continue
            o = beams[j]
            a2, c2 = np.array(o["a"]), np.array(o["b"])
            d2 = unit(c2 - a2)
            if abs(np.dot(d, d2)) < math.cos(math.radians(tol_ang)):
                continue
            w = a2 - a
            if abs(w[0] * d[1] - w[1] * d[0]) > tol_perp:
                continue
            s0, s1 = sorted([float(np.dot(a2 - a, d)), float(np.dot(c2 - a, d))])
            if s0 > t1 + 50 or s1 < t0 - 50:
                continue
            t0, t1 = min(t0, s0), max(t1, s1)
            used[j] = True
        used[i] = True
        out.append({**b, "a": a + d * t0, "b": a + d * t1})
    return out


def resolve(items, P=Params()):
    """간섭 정리(피드백 c1d6e4·ce4a4d). rank 가 낮은(우선) 항목부터 확정한다. 뒤 항목은 확정 항목과
    (a) 평행·겹침(거리 OVERLAP_PERP 안)이면 겹친 구간을 잘라내고(최우선 1개만 남김),
    (b) 교차하면 교차점에서 나눈다(SUB 보→MAIN 보, 보→거더, T접합 거더→기둥 거더 …).
    잘린 끝은 i/j=None, ka/kb="cut". MIN_PIECE 보다 짧은 조각은 버림."""
    if not items:
        return []
    order = sorted(range(len(items)), key=lambda k: (items[k].get("rank", 9), -seg_len(items[k])))
    geoms = [LineString([tuple(it["a"]), tuple(it["b"])]) for it in items]
    tree = STRtree(geoms)
    accepted = np.zeros(len(items), dtype=bool)
    cos_tol = math.cos(math.radians(1.5))
    out = []
    for k in order:
        it = items[k]
        a = np.asarray(it["a"], dtype=float); b = np.asarray(it["b"], dtype=float)
        L = float(np.linalg.norm(b - a))
        if L < 1:
            continue
        d = (b - a) / L
        cuts = []; blocked = []
        for idx in tree.query(geoms[k]):
            if idx == k or not accepted[idx]:
                continue
            o = items[idx]
            a2 = np.asarray(o["a"], dtype=float); b2 = np.asarray(o["b"], dtype=float)
            d2 = unit(b2 - a2)
            if abs(float(np.dot(d, d2))) >= cos_tol:  # 평행 → 겹침 검사
                w1 = a2 - a; w2 = b2 - a
                if abs(w1[0] * d[1] - w1[1] * d[0]) <= P.OVERLAP_PERP and abs(w2[0] * d[1] - w2[1] * d[0]) <= P.OVERLAP_PERP:
                    s0, s1 = sorted([float(np.dot(w1, d)), float(np.dot(w2, d))])
                    if s1 > 0 and s0 < L:
                        blocked.append((max(s0, 0.0), min(s1, L)))
                continue
            if geoms[k].crosses(geoms[idx]):
                q = geoms[k].intersection(geoms[idx])
                pts = [q] if q.geom_type == "Point" else list(getattr(q, "geoms", []))
                for p in pts:
                    if p.geom_type == "Point":
                        cuts.append(float(np.dot(np.array([p.x, p.y]) - a, d)))
        # 남는 구간 = [0,L] - 겹침, 그 안을 교차점에서 분할
        free = [(0.0, L)]
        for s0, s1 in sorted(blocked):
            nf = []
            for f0, f1 in free:
                if s1 <= f0 or s0 >= f1:
                    nf.append((f0, f1)); continue
                if s0 > f0:
                    nf.append((f0, s0))
                if s1 < f1:
                    nf.append((s1, f1))
            free = nf
        pieces = []
        for f0, f1 in free:
            ts = sorted({f0, f1, *[t for t in cuts if f0 < t < f1]})
            for t0, t1 in zip(ts[:-1], ts[1:]):
                if t1 - t0 >= P.MIN_PIECE:
                    pieces.append((t0, t1))
        if not pieces:
            continue
        accepted[k] = True
        for t0, t1 in pieces:
            q = dict(it); q["a"] = a + d * t0; q["b"] = a + d * t1
            if t0 > 0.5:
                q["i"] = None; q["ka"] = "cut"
            if t1 < L - 0.5:
                q["j"] = None; q["kb"] = "cut"
            out.append(q)
    return out


def to_segs(items):
    return np.array([[g["a"][0], g["a"][1], g["b"][0], g["b"][1]] for g in items]) if items else np.zeros((0, 4))
