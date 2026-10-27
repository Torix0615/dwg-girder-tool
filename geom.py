"""기하 공통: 프리미티브→선분, 표본점, 일치율 계산"""
import math
import numpy as np
from scipy.spatial import cKDTree


def arc_points(cx, cy, r, a1, a2, n=12):
    a1 %= 360; a2 %= 360
    sweep = (a2 - a1) % 360
    if sweep == 0:
        sweep = 360
    return [(cx + r * math.cos(math.radians(a1 + sweep * i / n)), cy + r * math.sin(math.radians(a1 + sweep * i / n))) for i in range(n + 1)]


def to_segments(prims, with_arcs=True):
    """프리미티브 목록 → (N,4) 선분 배열 [x1,y1,x2,y2]"""
    segs = []
    for p in prims:
        k = p["kind"]
        if k == "LINE":
            segs.append((p["x1"], p["y1"], p["x2"], p["y2"]))
        elif k == "POLY":
            pts = p["pts"]
            n = len(pts)
            rng = range(n) if p.get("closed") and n > 2 else range(n - 1)
            for i in rng:
                a = pts[i]; b = pts[(i + 1) % n]
                if abs(a[2]) > 1e-9 and with_arcs:
                    # bulge 호 → 꺾은선
                    bp = bulge_points(a, b)
                    for j in range(len(bp) - 1):
                        segs.append((bp[j][0], bp[j][1], bp[j + 1][0], bp[j + 1][1]))
                else:
                    segs.append((a[0], a[1], b[0], b[1]))
        elif k == "ARC" and with_arcs:
            ap = arc_points(p["cx"], p["cy"], p["r"], p["a1"], p["a2"])
            for j in range(len(ap) - 1):
                segs.append((ap[j][0], ap[j][1], ap[j + 1][0], ap[j + 1][1]))
        elif k == "CIRCLE" and with_arcs:
            ap = arc_points(p["cx"], p["cy"], p["r"], 0, 360, 16)
            for j in range(len(ap) - 1):
                segs.append((ap[j][0], ap[j][1], ap[j + 1][0], ap[j + 1][1]))
    if not segs:
        return np.zeros((0, 4))
    return np.array(segs, dtype=float)


def bulge_points(a, b, n=8):
    x1, y1, bulge = a[0], a[1], a[2]
    x2, y2 = b[0], b[1]
    theta = 4 * math.atan(bulge)
    d = math.hypot(x2 - x1, y2 - y1)
    if d < 1e-9:
        return [(x1, y1), (x2, y2)]
    r = d / (2 * math.sin(abs(theta) / 2))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    h = math.sqrt(max(r * r - (d / 2) ** 2, 0.0))
    nx, ny = -(y2 - y1) / d, (x2 - x1) / d
    s = 1 if theta > 0 else -1
    cx, cy = mx - s * nx * h, my - s * ny * h
    sa = math.atan2(y1 - cy, x1 - cx)
    pts = []
    for i in range(n + 1):
        ang = sa + theta * i / n
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def seg_len(segs):
    return np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])


def sample_points(segs, step=20.0):
    """선분을 step 간격으로 표본화 → (M,2)"""
    out = []
    L = seg_len(segs)
    for (x1, y1, x2, y2), l in zip(segs, L):
        n = max(int(l // step), 1)
        t = np.linspace(0, 1, n + 1)
        out.append(np.column_stack([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t]))
    if not out:
        return np.zeros((0, 2))
    return np.vstack(out)


def norm_segs(segs):
    """끝점 정렬(작은 점 먼저) → (N,4)"""
    s = segs.copy()
    swap = (s[:, 0] > s[:, 2]) | ((s[:, 0] == s[:, 2]) & (s[:, 1] > s[:, 3]))
    s[swap] = s[swap][:, [2, 3, 0, 1]]
    return s


def match_metrics(ref, mine, tol=1.0, step=20.0, cover_tol=15.0):
    """ref/mine: (N,4) 선분. 반환 dict: 선분 재현/정밀, 길이 재현/정밀, F1"""
    res = {"ref_n": len(ref), "my_n": len(mine), "ref_len": float(seg_len(ref).sum()) if len(ref) else 0.0,
           "my_len": float(seg_len(mine).sum()) if len(mine) else 0.0}
    if len(ref) == 0 or len(mine) == 0:
        res.update(seg_recall=0.0, seg_prec=0.0, len_recall=0.0, len_prec=0.0, f1=0.0)
        return res
    r = norm_segs(ref); m = norm_segs(mine)
    tr = cKDTree(r); tm = cKDTree(m)
    d, _ = tm.query(r, distance_upper_bound=tol * 1.5)
    res["seg_recall"] = float(np.isfinite(d).mean() * 100)
    d, _ = tr.query(m, distance_upper_bound=tol * 1.5)
    res["seg_prec"] = float(np.isfinite(d).mean() * 100)
    pr = sample_points(ref, step); pm = sample_points(mine, step)
    d, _ = cKDTree(pm).query(pr, distance_upper_bound=cover_tol)
    res["len_recall"] = float(np.isfinite(d).mean() * 100)
    d, _ = cKDTree(pr).query(pm, distance_upper_bound=cover_tol)
    res["len_prec"] = float(np.isfinite(d).mean() * 100)
    a, b = res["len_recall"], res["len_prec"]
    res["f1"] = 2 * a * b / (a + b) if a + b > 0 else 0.0
    return res


def find_offset(ref, mine, grid=1.0):
    """참조→내 좌표 평행이동 추정: 수직선 x·수평선 y 차이의 최빈값"""
    def axis_vals(segs):
        v = np.abs(segs[:, 2] - segs[:, 0]) < 1e-6
        h = np.abs(segs[:, 3] - segs[:, 1]) < 1e-6
        return segs[v][:, 0], segs[h][:, 1]
    rx, ry = axis_vals(ref); mx, my = axis_vals(mine)
    def mode_diff(a, b):
        if len(a) == 0 or len(b) == 0:
            return 0.0, 0
        a = np.unique(np.round(a / grid) * grid); b = np.unique(np.round(b / grid) * grid)
        if len(a) > 3000: a = a[np.linspace(0, len(a) - 1, 3000).astype(int)]
        if len(b) > 3000: b = b[np.linspace(0, len(b) - 1, 3000).astype(int)]
        diff = (b[None, :] - a[:, None]).ravel()
        vals, cnt = np.unique(np.round(diff / grid) * grid, return_counts=True)
        i = cnt.argmax()
        return float(vals[i]), int(cnt[i])
    dx, nx = mode_diff(rx, mx); dy, ny = mode_diff(ry, my)
    return dx, dy, nx, ny
