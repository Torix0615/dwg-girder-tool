"""2단계 구조 모델: 1단계 후보(s1_cand.pkl)에서 층별 기둥(직사각형)·벽(골조 선분)·중심선·OPEN·동 범위를 만든다.
python stage2_model.py out/s1_cand.pkl out/s2_model.pkl [--config config.json]
모델[층id] = {"cols": [ {cx,cy,ux,uy,hw,hh,poly(4x2),label} ], "con": (N,4) 벽 선분(기둥 변 제외), "con_th": 벽 두께, "cen": (N,4), "open": (N,4), "dong": [polygon], "bbox"}
층 id·이름·기준점은 "floors" 에 그대로 전달.
"""
import sys, pickle, re, math
import numpy as np
from geom import to_segments

from cfg import pop_config_arg
CFG, argv = pop_config_arg(sys.argv[1:])
src, out = argv[0], argv[1]
C = pickle.load(open(src, "rb"))  # 내 스크립트 산출물(신뢰)
floors, cand = C["floors"], C["cand"]


def rect_info(P):
    P = np.asarray(P, dtype=float)[:4]
    c = P.mean(axis=0)
    e0 = P[1] - P[0]; e1 = P[2] - P[1]
    l0, l1 = np.linalg.norm(e0), np.linalg.norm(e1)
    if l0 < 1 or l1 < 1:
        return None
    cand_axes = [(e0 / l0, l0, l1), (e1 / l1, l1, l0)]
    ux, hw, hh = min(cand_axes, key=lambda t: min(abs(math.atan2(t[0][1], t[0][0])) % math.pi, math.pi - abs(math.atan2(t[0][1], t[0][0])) % math.pi))
    if ux[0] < 0:
        ux = -ux
    uy = np.array([-ux[1], ux[0]])
    return {"cx": c[0], "cy": c[1], "ux": ux, "uy": uy, "hw": hw / 2, "hh": hh / 2, "poly": P, "label": "",
            "ang": math.degrees(math.atan2(ux[1], ux[0]))}


def wall_thickness(con, dmin=100, dmax=700, overlap=0.5):
    """각 선분의 평행 짝(100~700mm) 거리 = 벽 두께. 짝 없으면 NaN"""
    from scipy.spatial import cKDTree
    n = len(con)
    th = np.full(n, np.nan)
    if n == 0:
        return th
    d = con[:, 2:] - con[:, :2]; L = np.hypot(d[:, 0], d[:, 1])
    u = d / np.maximum(L, 1e-9)[:, None]
    mid = (con[:, :2] + con[:, 2:]) / 2
    t = cKDTree(mid)
    for i in range(n):
        if L[i] < 150:
            continue
        best = None
        for j in t.query_ball_point(mid[i], L[i] / 2 + dmax + 50):
            if j == i or L[j] < 150 or abs(np.dot(u[i], u[j])) < 0.9994:
                continue
            w = mid[j] - mid[i]; perp = abs(w[0] * u[i][1] - w[1] * u[i][0])
            if not (dmin <= perp <= dmax):
                continue
            pj = [np.dot(con[j, :2] - con[i, :2], u[i]), np.dot(con[j, 2:] - con[i, :2], u[i])]
            lo = max(0.0, min(pj)); hi = min(L[i], max(pj))
            if hi - lo >= overlap * min(L[i], L[j]) and (best is None or perp < best):
                best = perp
        if best is not None:
            th[i] = best
    return th


def drop_col_edges(segs, cols, tol=5.0):
    """기둥 직사각형 변 위에 놓인 선분 제거(벽 선분만 남김)"""
    if not len(segs) or not cols:
        return segs
    from shapely.geometry import Polygon, Point
    from shapely.strtree import STRtree
    polys = [Polygon([tuple(v) for v in c["poly"]]) for c in cols]
    tree = STRtree(polys)
    keep = np.ones(len(segs), dtype=bool)
    for i, s in enumerate(segs):
        a, b = Point(s[0], s[1]), Point(s[2], s[3])
        for j in tree.query(a.buffer(tol)):
            ext = polys[j].exterior
            if ext.distance(a) <= tol and ext.distance(b) <= tol:
                keep[i] = False; break
    return segs[keep]


model = {}
for f in floors:
    k = f["id"]
    c = cand[k]
    cols = []
    for P in c.get("cols", []):
        r = rect_info(P)
        if r and 150 <= 2 * r["hw"] <= 2500 and 150 <= 2 * r["hh"] <= 2500:
            cols.append(r)
    labels = [(p["x"], p["y"], p["s"]) for p in c.get("text", [])]
    if labels and cols:
        from scipy.spatial import cKDTree
        t = cKDTree(np.array([[l[0], l[1]] for l in labels]))
        for r in cols:
            d, i = t.query([r["cx"], r["cy"]])
            r["label"] = labels[i][2] if d < 2500 else ""
    con = drop_col_edges(to_segments(c["golf"]), cols)
    con_th = wall_thickness(con)
    dong = []
    dsegs = to_segments(c.get("def", []))
    if len(dsegs):
        dl = np.hypot(dsegs[:, 2] - dsegs[:, 0], dsegs[:, 3] - dsegs[:, 1])
        dsegs = dsegs[dl <= float(CFG["동_선_최대길이"])]
        from shapely.geometry import LineString
        from shapely.ops import unary_union
        import shapely
        R = 1200.0
        u = unary_union([LineString([(s[0], s[1]), (s[2], s[3])]) for s in dsegs]).buffer(R, join_style=2)
        geoms = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
        for g in geoms:
            g = shapely.concave_hull(g, ratio=0.3).buffer(-R, join_style=2)
            if g.is_empty:
                continue
            parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
            for q in parts:
                if q.area >= float(CFG["동_최소면적_m2"]) * 1e6:
                    dong.append(q.simplify(50))
    model[k] = {"cols": cols, "con": con, "con_th": con_th, "wallb": np.zeros((0, 4)), "cen": to_segments(c["cen"]), "open": to_segments(c["open"]),
                "dong": dong, "bbox": f["bbox"]}
    angs = np.array([r["ang"] for r in cols]) if cols else np.zeros(0)
    print(f"{f['short']:7}: 기둥 {len(cols)}개 (0°:{(np.abs(angs)<1).sum()} 기타:{(np.abs(angs)>=1).sum()}), 벽 선분 {len(con)}(구조벽≥250: {int(np.nansum(con_th >= 250))}, 짝없음: {int(np.isnan(con_th).sum())}), 중심선 {len(model[k]['cen'])}, 동 {len(dong)}개")
pickle.dump({"floors": floors, "model": model}, open(out, "wb"), protocol=5)
print("saved", out)
