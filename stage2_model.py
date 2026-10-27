"""2단계 구조 모델: 1단계 후보(s1_cand.pkl)에서 층별 기둥(사각형)·벽(CON 선분)·OPEN·범위를 만든다.
python stage2_model.py out/s1_cand.pkl out/s2_model.pkl
모델[k] = {"cols": [ {cx,cy,ux,uy,hw,hh,poly(4x2),label} ], "con": (N,4) 벽/콘크리트 선분, "wallb": (N,4),
            "cen": (N,4), "open": (N,4), "band": (ymin,ymax)}
좌표는 원본 좌표(해당 층 띠). 사용 시 그릴 층 띠로 y 이동.
"""
import sys, pickle, re, math
import numpy as np
from geom import to_segments

from cfg import pop_config_arg
CFG, argv = pop_config_arg(sys.argv[1:])
src, out = argv[0], argv[1]
C = pickle.load(open(src, "rb"))  # 내 스크립트 산출물
FY, H, cand = C["FY"], C["H"], C["cand"]
COL_L = CFG["기둥_레이어"]; CON_L = [l for l in CFG["골조_레이어"] if l != COL_L] or CFG["골조_레이어"]


def rect_info(pts):
    P = np.array([[q[0], q[1]] for q in pts[:4]], dtype=float)
    c = P.mean(axis=0)
    e0 = P[1] - P[0]; e1 = P[2] - P[1]
    l0, l1 = np.linalg.norm(e0), np.linalg.norm(e1)
    if l0 < 1 or l1 < 1:
        return None
    # ux = X 축에 가까운 변 방향
    cand_axes = [(e0 / l0, l0, l1), (e1 / l1, l1, l0)]
    ux, hw, hh = min(cand_axes, key=lambda t: min(abs(math.atan2(t[0][1], t[0][0])) % math.pi, math.pi - abs(math.atan2(t[0][1], t[0][0])) % math.pi))
    if ux[0] < 0:
        ux = -ux
    uy = np.array([-ux[1], ux[0]])
    return {"cx": c[0], "cy": c[1], "ux": ux, "uy": uy, "hw": hw / 2, "hh": hh / 2, "poly": P,
            "ang": math.degrees(math.atan2(ux[1], ux[0]))}


def wall_thickness(con, dmin=100, dmax=700, overlap=0.5):
    """각 CON 선분의 평행 짝(100~700mm) 거리 = 벽 두께. 짝 없으면 NaN"""
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


model = {}
for k in sorted(cand):
    c = cand[k]
    cols = []
    for p in c["golf"]:
        if p["layer"] == COL_L and p["kind"] == "POLY" and p.get("closed") and len(p["pts"]) in (4, 5):
            r = rect_info(p["pts"])
            if r and 150 <= 2 * r["hw"] <= 2500 and 150 <= 2 * r["hh"] <= 2500:
                cols.append(r)
    # 라벨(기둥 크기) 붙이기
    labels = [(p["x"], p["y"], p["s"]) for p in c["text"] if p["layer"] == "CHECK-지하주차장 기둥"]
    if labels and cols:
        from scipy.spatial import cKDTree
        t = cKDTree(np.array([[l[0], l[1]] for l in labels]))
        for r in cols:
            d, i = t.query([r["cx"], r["cy"]])
            r["label"] = labels[i][2] if d < 2500 else ""
    con = to_segments([p for p in c["golf"] if p["layer"] in CON_L])
    con_th = wall_thickness(con)
    # 동(아파트) 범위: 기준층 벽체(DEF-기준층 벽체) 선분을 버퍼로 묶어 연결 성분별 외곽 폴리곤
    dong = []
    dsegs = to_segments(c.get("def", []))
    if len(dsegs):
        dl = np.hypot(dsegs[:, 2] - dsegs[:, 0], dsegs[:, 3] - dsegs[:, 1])
        dsegs = dsegs[dl <= float(CFG["동_선_최대길이"])]  # 대지경계선 등 긴 선 제외
        from shapely.geometry import LineString
        from shapely.ops import unary_union
        from shapely.geometry import Polygon
        R = 1200.0
        u = unary_union([LineString([(s[0], s[1]), (s[2], s[3])]) for s in dsegs]).buffer(R, join_style=2)
        geoms = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
        import shapely
        for g in geoms:
            g = shapely.concave_hull(g, ratio=0.3).buffer(-R, join_style=2)  # 오목 외곽 → 원래 크기로
            if g.is_empty:
                continue
            parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
            for q in parts:
                if q.area >= float(CFG["동_최소면적_m2"]) * 1e6:  # 150 m² 이상만 동으로
                    dong.append(q.simplify(50))
    model[k] = {
        "cols": cols,
        "con": con,
        "con_th": con_th,
        "wallb": to_segments(c["wallb"]),
        "cen": to_segments([p for p in c["cen"] if p["layer"] == "CEN"]),
        "open": to_segments(c["open"]),
        "dong": dong,
        "band": (FY[k] - H, FY[k]),
    }
    angs = np.array([r["ang"] for r in cols])
    print(f"B{k}: 기둥 {len(cols)}개 (각도 분포 0°:{(np.abs(angs)<1).sum()} 7°:{((angs>5)&(angs<9)).sum()} 기타:{((np.abs(angs)>=1)&~((angs>5)&(angs<9))).sum()}), CON 선분 {len(con)}(구조벽≥250: {int(np.nansum(con_th >= 250))}, 200mm: {int(np.nansum((con_th > 150) & (con_th < 250)))}, 짝없음: {int(np.isnan(con_th).sum())}), WALL-B {len(model[k]['wallb'])}, 동 {len(dong)}개 (면적 m²: {sorted(round(g.area/1e6) for g in dong)})")
pickle.dump({"FY": FY, "H": H, "model": model}, open(out, "wb"), protocol=5)
print("saved", out)
