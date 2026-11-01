"""최종 DXF(원본 미포함, ezdxf R2010 신규 문서): 층별 블록 <층>_골조(1단계 골조/기둥/중심선/OPEN + 2단계 하부골조/GIRDER/BEAM/동 구역). 층 위치는 원본 그대로.
python final_write.py out/s1_cand.pkl out/s2_model.pkl out/s2_result.pkl out/최종.dxf
"""
import sys, re, math, time, pickle
import numpy as np
import ezdxf
from shapely.geometry import LineString, Polygon, Point
from shapely.strtree import STRtree
import stage2_engine as E

from cfg import pop_config_arg
CFG, argv = pop_config_arg(sys.argv[1:])
cand_p, model_p, result_p, out_p = argv[0:4]
GW_X, GW_Y, BW = float(CFG["거더폭_X"]), float(CFG["거더폭_Y"]), float(CFG["보폭"])
OL = CFG["출력_레이어"]
L_GOLF, L_CEN, L_OPEN = OL["골조"], OL["중심선"], OL["OPEN"]
L_G, L_B, L_LOW, L_DONG = OL["거더"], OL["보"], OL["하부골조"], OL["동구역"]
C = pickle.load(open(cand_p, "rb")); cand = C["cand"]
model = pickle.load(open(model_p, "rb"))["model"]
RES = pickle.load(open(result_p, "rb")); result = RES["result"]; floors = RES["floors"]
SHORT = {f["id"]: f["short"] for f in floors}; ANCHOR = {f["id"]: f["anchor"] for f in floors}
t0 = time.time()
doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 4  # mm
msp = doc.modelspace()
print("linetypes:", [lt.dxf.name for lt in doc.linetypes][:40])
for nm, pat in (("HIDDEN", [0.375, 0.25, -0.125]), ("CENTER", [2.0, 1.25, -0.25, 0.25, -0.25]), ("DASHED", [0.75, 0.5, -0.25])):
    if nm not in doc.linetypes:
        doc.linetypes.add(nm, pattern=pat)
L_WARN = OL.get("경고", "----- (구조) 경고")
L_CG, L_GG, L_BG = OL.get("기둥중심", "COLUMN(GEN)"), OL.get("거더중심", "GIRDER(GEN)"), OL.get("보중심", "BEAM(GEN)")
L_WG, L_WGAP = OL.get("벽중심", "WALL(GEN)"), OL.get("벽중심_끊김", "WALL(GEN)-GAP")
for name, color, lt in ((L_GOLF, 2, "CONTINUOUS"), (L_CEN, 1, "CENTER"), (L_OPEN, 8, "CONTINUOUS"),
                        (L_G, 3, "HIDDEN"), (L_B, 4, "HIDDEN"), (L_LOW, 6, "HIDDEN"), (L_DONG, 5, "DASHED"), (L_WARN, 1, "CONTINUOUS"),
                        (L_CG, 6, "CONTINUOUS"), (L_GG, 3, "CENTER"), (L_BG, 4, "CENTER"), (L_WG, 30, "CENTER"), (L_WGAP, 1, "CONTINUOUS")):
    doc.layers.add(name, color=color, linetype=lt)


def wall_centerlines(m):
    """벽 짝(평행 두 선, 두께 th) → 중심선(두 선 사이 th/2). 짝 없는 단일선은 제외. 같은 선 위 조각은 합침."""
    con, th, pair = m["con"], np.asarray(m["con_th"]), np.asarray(m.get("con_pair", np.full(len(m["con"]), -1)))
    items = []
    for i in range(len(con)):
        j = int(pair[i]) if i < len(pair) else -1
        if j < 0 or not np.isfinite(th[i]):
            continue
        a = con[i, :2]; b = con[i, 2:]
        d = unit(b - a); nrm = np.array([-d[1], d[0]])
        mj = (con[j, :2] + con[j, 2:]) / 2
        sgn = 1.0 if np.dot(mj - a, nrm) > 0 else -1.0
        o = nrm * sgn * (th[i] / 2)
        items.append({"a": a + o, "b": b + o})
    return E.merge_collinear(items, tol_perp=40.0) if items else []


def wall_gaps(lines, gap_min=50.0, gap_max=3000.0, tol_perp=40.0):
    """같은 직선 위 벽 중심선 조각 사이의 빈 구간(gap_min~gap_max) → 끊김 강조 선"""
    if len(lines) < 2:
        return []
    geoms = [LineString([tuple(w["a"]), tuple(w["b"])]) for w in lines]
    tree = STRtree(geoms)
    cos_tol = math.cos(math.radians(1.5)); out = []; seen = set()
    for i, w in enumerate(lines):
        a = np.asarray(w["a"]); b = np.asarray(w["b"]); d = unit(b - a); L = float(np.linalg.norm(b - a))
        for j in tree.query(geoms[i].buffer(gap_max)):
            j = int(j)
            if j == i or (min(i, j), max(i, j)) in seen:
                continue
            o = lines[j]; a2 = np.asarray(o["a"]); b2 = np.asarray(o["b"]); d2 = unit(b2 - a2)
            if abs(float(np.dot(d, d2))) < cos_tol:
                continue
            w1 = a2 - a; w2 = b2 - a
            if abs(w1[0] * d[1] - w1[1] * d[0]) > tol_perp or abs(w2[0] * d[1] - w2[1] * d[0]) > tol_perp:
                continue
            s0, s1 = sorted([float(np.dot(w1, d)), float(np.dot(w2, d))])
            gap = s0 - L if s0 > L else (-s1 if s1 < 0 else -1.0)
            if gap_min <= gap <= gap_max:
                seen.add((min(i, j), max(i, j)))
                out.append((a + d * L, a + d * s0) if s0 > L else (a + d * s1, a))
    return out


def add_gen(blk, m, G, B, dx, dy):
    """2단계 맨 끝(피드백 e4cc34): COLUMN(GEN) 기둥 안 X / GIRDER(GEN)·BEAM(GEN) 중심선 / WALL(GEN) 벽 중심선 + 끊김 강조"""
    n = 0
    for c in m["cols"]:
        P4 = np.asarray(c["poly"][:4], dtype=float); ctr = np.array([c["cx"], c["cy"]])
        Q = ctr + (P4 - ctr) * 0.9  # 기둥 안쪽(90%)에서 대각선 X → 기둥 밖으로 나가지 않음
        blk.add_line((Q[0][0] + dx, Q[0][1] + dy), (Q[2][0] + dx, Q[2][1] + dy), dxfattribs={"layer": L_CG})
        blk.add_line((Q[1][0] + dx, Q[1][1] + dy), (Q[3][0] + dx, Q[3][1] + dy), dxfattribs={"layer": L_CG}); n += 2
    for s in G:
        blk.add_line((s[0], s[1]), (s[2], s[3]), dxfattribs={"layer": L_GG}); n += 1
    for s in B:
        blk.add_line((s[0], s[1]), (s[2], s[3]), dxfattribs={"layer": L_BG}); n += 1
    wl = wall_centerlines(m)
    for w in wl:
        blk.add_line((w["a"][0] + dx, w["a"][1] + dy), (w["b"][0] + dx, w["b"][1] + dy), dxfattribs={"layer": L_WG}); n += 1
    gaps = wall_gaps(wl)
    for p, q in gaps:
        blk.add_line((p[0] + dx, p[1] + dy), (q[0] + dx, q[1] + dy), dxfattribs={"layer": L_WGAP, "lineweight": 50}); n += 1
    print(f"  GEN 중심선 {n}개 (기둥 {len(m['cols'])} 거더 {len(G)} 보 {len(B)} 벽 {len(wl)} 끊김 {len(gaps)})", flush=True)
    return n


def add_warnings(blk, R, m, dx, dy):
    """2단계 규칙 4: 불안정·비지지 조건을 경고 레이어에 표시.
    - 비지지 기둥: 거더가 하나도 닿지 않는 기둥
    - 1방향 지지: 거더가 한 축 방향으로만 있는 기둥(직교 방향 지지 없음)
    - 거더 위 지지: 기둥·벽이 아니라 다른 거더에 T 접합으로 얹힌 거더 끝"""
    cols = m["cols"]; n = 0
    per_col = {i: [] for i in range(len(cols))}
    for g in R["girders"]:
        d = np.array(g["b"]) - np.array(g["a"]); L = np.hypot(*d)
        if L < 1:
            continue
        d = d / L
        for idx in (g.get("i"), g.get("j")):
            if idx is not None and idx in per_col:
                per_col[idx].append(d)
    def mark(x, y, label, r=800):
        blk.add_circle((x + dx, y + dy), r, dxfattribs={"layer": L_WARN})
        blk.add_text(label, height=300, dxfattribs={"layer": L_WARN}).set_placement((x + dx + r + 100, y + dy))
    for i, c in enumerate(cols):
        ds = per_col[i]
        if not ds:
            mark(c["cx"], c["cy"], "비지지 기둥(거더 없음)"); n += 1; continue
        ux = np.asarray(c["ux"]); along_x = [abs(float(np.dot(d, ux))) > 0.7 for d in ds]
        if all(along_x) or not any(along_x):
            mark(c["cx"], c["cy"], "1방향 지지(직교 거더 없음)", r=700); n += 1
    for g in R["girders"]:
        if g.get("kb") == "girder":
            mark(g["b"][0], g["b"][1], "거더 위 지지(T접합)", r=400); n += 1
    return n


def add_prims(layout, prims, layer):
    n = 0
    for p in prims:
        k = p["kind"]; attr = {"layer": layer}
        if k == "LINE":
            layout.add_line((p["x1"], p["y1"]), (p["x2"], p["y2"]), dxfattribs=attr)
        elif k == "POLY":
            layout.add_lwpolyline([(q[0], q[1], 0, 0, q[2]) for q in p["pts"]], format="xyseb", close=p.get("closed", False), dxfattribs=attr)
        elif k == "ARC":
            layout.add_arc((p["cx"], p["cy"]), p["r"], p["a1"], p["a2"], dxfattribs=attr)
        elif k == "CIRCLE":
            layout.add_circle((p["cx"], p["cy"]), p["r"], dxfattribs=attr)
        elif k == "TEXT":
            layout.add_text(p["s"], height=p["h"], rotation=p.get("rot", 0), dxfattribs=attr).set_placement((p["x"], p["y"]))
        else:
            continue
        n += 1
    return n


def unit(v):
    n = np.linalg.norm(v); return v / n if n else v


def exit_point(inter, start, other):
    pts = []
    geoms = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
    for q in geoms:
        if q.geom_type == "Point":
            pts.append(np.array([q.x, q.y]))
    if not pts:
        return start
    d = unit(np.array(other) - np.array(start))
    return max(pts, key=lambda p: np.dot(p - np.array(start), d))


def double_lines(layout, segs, width, layer, col_polys, col_tree, shift):
    n_added = 0
    for s in segs:
        a_pt = np.array(s[:2]); b_pt = np.array(s[2:])
        if np.linalg.norm(b_pt - a_pt) < 1:
            continue
        d = unit(b_pt - a_pt); nrm = np.array([-d[1], d[0]])
        for sgn in (1, -1):
            o = nrm * (width / 2) * sgn
            p1, p2 = a_pt + o, b_pt + o
            ls = LineString([tuple(p1), tuple(p2)])
            for idx in col_tree.query(ls):
                ob = col_polys[idx]
                if ob.contains(Point(p1)):
                    p1 = exit_point(ls.intersection(ob.exterior), p1, p2)
                if ob.contains(Point(p2)):
                    p2 = exit_point(ls.intersection(ob.exterior), p2, p1)
            if np.linalg.norm(p2 - p1) < 1:
                continue
            layout.add_line((p1[0], p1[1] + shift), (p2[0], p2[1] + shift), dxfattribs={"layer": layer})
            n_added += 1
    return n_added


def is_xish(s):
    ang = abs(math.degrees(math.atan2(s[3] - s[1], s[2] - s[0]))) % 180
    return ang < 45 or ang > 135


def add_stage2(blk, N, R, shift):
    """shift=(dx,dy): 지지층 좌표 → N 층 위치"""
    k = R["support"]
    m = model[k]
    dx, dy = shift
    n_low = 0
    for c in m["cols"]:
        blk.add_lwpolyline([(p[0] + dx, p[1] + dy) for p in c["poly"]], close=True, dxfattribs={"layer": L_LOW}); n_low += 1
    for s in m["con"]:
        blk.add_line((s[0] + dx, s[1] + dy), (s[2] + dx, s[3] + dy), dxfattribs={"layer": L_LOW}); n_low += 1
    col_polys = [Polygon([(v[0] + dx, v[1] + dy) for v in c["poly"]]) for c in m["cols"]]; col_tree = STRtree(col_polys)
    off = np.array([dx, dy, dx, dy])
    G = E.to_segs(R["girders"]) + off if R["girders"] else np.zeros((0, 4)); B = E.to_segs(R["beams"]) + off if R["beams"] else np.zeros((0, 4))
    ng = sum(double_lines(blk, [s], GW_X if is_xish(s) else GW_Y, L_G, col_polys, col_tree, 0.0) for s in G)
    nb = double_lines(blk, B, BW, L_B, col_polys, col_tree, 0.0)
    for dg in m.get("dong", []):
        blk.add_lwpolyline([(x + dx, y + dy) for x, y in dg.exterior.coords], close=True, dxfattribs={"layer": L_DONG})
    nw = add_warnings(blk, R, m, dx, dy)
    print(f"  경고 표시 {nw}개", flush=True)
    add_gen(blk, m, G, B, dx, dy)
    return n_low, ng, nb


DX = float(CFG["출력_x이동"])  # 0 = 원본 좌표 그대로
for f in floors:
    N = f["id"]; bname = re.sub(r'[<>/\\":;?*|=`,]', "_", f"{f['short']}_골조")  # 블록 이름 금지 문자 치환
    blk = doc.blocks.new(name=bname)
    k1 = k2 = k3 = 0
    if N in cand:
        c = cand[N]
        k1 = add_prims(blk, c["golf"], L_GOLF)
        for P in c.get("cols", []):  # 기둥 직사각형(4선 기둥도 폴리선으로)
            blk.add_lwpolyline([(p[0], p[1]) for p in P[:4]], close=True, dxfattribs={"layer": L_GOLF})
        k2 = add_prims(blk, c["cen"], L_CEN)
        k3 = add_prims(blk, c["open"] + c["open_text"], L_OPEN)
    s2 = (0, 0, 0)
    if N in result:
        s2 = add_stage2(blk, N, result[N], result[N]["shift"])
    ins = msp.add_blockref(bname, (DX, 0.0), dxfattribs={"layer": L_GOLF})
    g = doc.groups.new(name=f"GRP_{bname}"); g.extend([ins])
    sup = SHORT.get(result[N]["support"]) if N in result else None
    ax, ay = ANCHOR[N]
    msp.add_text(f"{f['short']} 골조" + (f" (거더·보는 {sup} 기둥 기준)" if sup else " (최하층, 거더 없음)" if N == floors[0]["id"] else ""),
                 height=2500, dxfattribs={"layer": L_GOLF}).set_placement((DX + ax, ay - 6000))
    print(f"{bname}: 골조 {k1} 중심선 {k2} OPEN {k3} | 하부골조 {s2[0]} 거더선 {s2[1]} 보선 {s2[2]}")
doc.saveas(out_p)
print(f"saved {out_p} {time.time()-t0:.0f}s")
