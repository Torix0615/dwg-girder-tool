"""최종 DXF(원본 미포함, ezdxf R2010 신규 문서): 층별 블록 B1~B6_골조(1단계 골조/중심선/OPEN + 2단계 하부골조/GIRDER/BEAM/동 구역) + 1F_골조.
python final_write.py out/s1_cand.pkl out/s2_model.pkl out/s2_result.pkl out/최종.dxf
"""
import sys, math, time, pickle
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
GOLF_L = set(CFG["골조_레이어"]) | {CFG["기둥_레이어"]}; CEN_L = set(CFG["중심선_레이어"])

C = pickle.load(open(cand_p, "rb")); cand = C["cand"]; FY = C["FY"]; H = C["H"]
model = pickle.load(open(model_p, "rb"))["model"]
result = pickle.load(open(result_p, "rb"))["result"]
t0 = time.time()
doc = ezdxf.new("R2010", setup=True)
doc.header["$INSUNITS"] = 4  # mm
msp = doc.modelspace()
print("linetypes:", [lt.dxf.name for lt in doc.linetypes][:40])
for nm, pat in (("HIDDEN", [0.375, 0.25, -0.125]), ("CENTER", [2.0, 1.25, -0.25, 0.25, -0.25]), ("DASHED", [0.75, 0.5, -0.25])):
    if nm not in doc.linetypes:
        doc.linetypes.add(nm, pattern=pat)
for name, color, lt in ((L_GOLF, 2, "CONTINUOUS"), (L_CEN, 1, "CENTER"), (L_OPEN, 8, "CONTINUOUS"),
                        (L_G, 3, "HIDDEN"), (L_B, 4, "HIDDEN"), (L_LOW, 6, "HIDDEN"), (L_DONG, 5, "DASHED")):
    doc.layers.add(name, color=color, linetype=lt)


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
    k = R["support"]
    m = model[k]
    n_low = 0
    for c in m["cols"]:
        blk.add_lwpolyline([(p[0], p[1] + shift) for p in c["poly"]], close=True, dxfattribs={"layer": L_LOW}); n_low += 1
    for s in m["con"]:
        blk.add_line((s[0], s[1] + shift), (s[2], s[3] + shift), dxfattribs={"layer": L_LOW}); n_low += 1
    col_polys = [Polygon([tuple(v) for v in c["poly"]]) for c in m["cols"]]; col_tree = STRtree(col_polys)
    G = E.to_segs(R["girders"]); B = E.to_segs(R["beams"])
    ng = sum(double_lines(blk, [s], GW_X if is_xish(s) else GW_Y, L_G, col_polys, col_tree, shift) for s in G)
    nb = double_lines(blk, B, BW, L_B, col_polys, col_tree, shift)
    for dg in m.get("dong", []):
        blk.add_lwpolyline([(x, y + shift) for x, y in dg.exterior.coords], close=True, dxfattribs={"layer": L_DONG})
    return n_low, ng, nb


DX = float(CFG["출력_x이동"])  # 0 = 원본 좌표 그대로
for N in sorted(cand):
    bname = f"B{N}_골조"
    blk = doc.blocks.new(name=bname)
    c = cand[N]
    k1 = add_prims(blk, [p for p in c["golf"] if p["layer"] in GOLF_L], L_GOLF)
    k2 = add_prims(blk, [p for p in c["cen"] if p["layer"] in CEN_L], L_CEN)
    k3 = add_prims(blk, c["open"] + c["open_text"], L_OPEN)
    s2 = (0, 0, 0)
    if N in result:
        s2 = add_stage2(blk, N, result[N], result[N]["shift"])
    ins = msp.add_blockref(bname, (DX, 0.0), dxfattribs={"layer": L_GOLF})
    g = doc.groups.new(name=f"GRP_{bname}"); g.extend([ins])
    print(f"{bname}: 골조 {k1} 중심선 {k2} OPEN {k3} | 하부골조 {s2[0]} 거더선 {s2[1]} 보선 {s2[2]}")
if 0 in result:
    blk = doc.blocks.new(name="1F_골조")
    s2 = add_stage2(blk, 0, result[0], H)  # B1 띠 바로 위
    ins = msp.add_blockref("1F_골조", (DX, 0.0), dxfattribs={"layer": L_GOLF})
    g = doc.groups.new(name="GRP_1F_골조"); g.extend([ins])
    print(f"1F_골조(B1 기둥 기준, B1 띠 위): 하부골조 {s2[0]} 거더선 {s2[1]} 보선 {s2[2]}")
# 층 라벨
NMAX = max(cand)
for N in sorted(cand):
    msp.add_text(f"B{N} 골조 (거더·보는 B{N+1} 기둥 기준)" if N < NMAX else f"B{N} 골조 (최하층, 거더 없음)", height=8000,
                 dxfattribs={"layer": L_GOLF}).set_placement((DX + 60000, FY[N] - 20000))
if 0 in result:
    msp.add_text("1F 바닥 거더·보 (B1 기둥 기준)", height=8000, dxfattribs={"layer": L_GOLF}).set_placement((DX + 60000, FY[1] + H - 20000))
doc.saveas(out_p)
print(f"saved {out_p} {time.time()-t0:.0f}s")
