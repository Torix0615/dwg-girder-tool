"""2단계 엔진: 지지층(k) 구조(기둥·벽)에서 거더·보 중심선을 생성.
규칙
 1. 모든 선은 기둥 중심 기준(중심→중심).
 2. 기둥의 4방향(기둥 사각형 축 ±ux, ±uy)으로 가장 가까운 기둥(각도 ±ANG° 안)을 찾아 GIRDER.
 3. 인접 기둥끼리만: 방향별 최근접 1개, 사이에 벽이 가로막으면 벽 면까지만.
    기둥이 없으면 벽 면까지(Lmax 안), 벽도 없으면 기존 거더에 T 접합(벽이 먼저면 벽).
 4/5. 거더·벽으로 둘러싸인 베이(폴리곤)마다: Y방향 변 > SPLIT 이면 X방향(가까운 축) 보를 베이 중앙에,
      아니고 X방향 변 > SPLIT 이면 Y방향 보. (X 우선)
 6. 동(아파트) 폴리곤 안의 기둥은 주차장 거더 생성에서 제외(별도 파일 처리).
반환: girders=[{a,b,ka,kb,i,j}], beams=[{a,b,xish,bay}]
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


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def col_extent(col, d):
    return max(abs(np.dot(v - np.array([col["cx"], col["cy"]]), d)) for v in col["poly"])


def seg_dir(s):
    return unit(np.array([s[2] - s[0], s[3] - s[1]]))


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
    tan_ang = math.tan(math.radians(P.ANG))
    for i, c in enumerate(cols):
        ci = centers[i]
        for d in (c["ux"], -c["ux"], c["uy"], -c["uy"]):
            d = unit(d)
            v = centers - ci
            along = v @ d
            perp = np.abs(v[:, 0] * d[1] - v[:, 1] * d[0])
            ok = (along > 100) & (along <= P.LMAX) & (perp <= np.maximum(P.PERP_MIN, along * tan_ang))
            ok[i] = False
            j = None
            if ok.any():
                cand = np.where(ok)[0]
                j = int(cand[np.argmin(along[cand])])
            start = ci + d * (col_extent(c, d) + 5)
            wh = ray_hit(start, d, P.LMAX, walls, wgeoms, wtree, P.WALL_CROSS_DEG) if P.WALL_GIRDER else None
            if j is not None:
                aj = along[j]
                ext_j = col_extent(cols[j], d)
                blocked = wh is not None and (wh[0] + np.dot(start - ci, d)) < aj - ext_j - 50
                if not blocked:
                    key = (min(i, j), max(i, j))
                    if key not in pair_set:
                        pair_set.add(key)
                        girders.append({"a": ci, "b": centers[j], "ka": "col", "kb": "col", "i": i, "j": j})
                    continue
            if wh is not None:
                hp = wh[1]
                if np.linalg.norm(hp - ci) >= P.MIN_GIRDER:
                    girders.append({"a": ci, "b": hp, "ka": "col", "kb": "wall", "i": i, "j": None})
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
                girders.append({"a": ci, "b": gh[1], "ka": "col", "kb": "girder", "i": i, "j": None})
    # 보 계산은 구조벽(두께 ≥ BEAM_WALL_TH)만 경계로 사용
    if con_th is not None:
        th = np.asarray(con_th)
        Lc = np.hypot(con[:, 2] - con[:, 0], con[:, 3] - con[:, 1])
        walls_b = con[(Lc >= P.WALL_MIN_LEN) & (((th >= P.BEAM_WALL_TH) & (th <= 700)) | (np.isnan(th) & (Lc >= P.BEAM_WALL_SINGLE)))]
    else:
        walls_b = walls
    beams = make_beams(girders, walls_b, P, cols) if girders else []
    return girders, beams


def make_beams(girders, walls, P, cols=None):
    """띠(strip) 방식: 각 거더의 양쪽으로 수직 광선을 쏴 반대편 경계(거더/벽/기둥)까지 거리 D 를 잰다.
    D 가 일정하고 > SPLIT 이면 거더와 평행한 보를 D/2 에 둔다. X방향 보 우선(교차하는 Y 보 제거)."""
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
    # X 우선
    xb = [LineString([tuple(b["a"]), tuple(b["b"])]) for b in raw if b["xish"]]
    keep = []
    if xb:
        xt = STRtree(xb)
        for b in raw:
            if b["xish"]:
                keep.append(b); continue
            ls = LineString([tuple(b["a"]), tuple(b["b"])])
            if not any(ls.crosses(xb[idx]) for idx in xt.query(ls)):
                keep.append(b)
    else:
        keep = raw
    return merge_collinear(keep)


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


def to_segs(items):
    return np.array([[g["a"][0], g["a"][1], g["b"][0], g["b"][1]] for g in items]) if items else np.zeros((0, 4))
