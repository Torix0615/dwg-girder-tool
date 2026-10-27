"""2단계 DXF 출력: 1단계 결과 DXF 를 열어 층별 골조 블록 안에 거더(GIRDER)·보(BEAM) 2중선과 하부 골조(지지층 기둥·벽) 오버레이를 추가.
동(아파트) 구역은 별도 파일(동_B{k}_{i}.dxf)로 저장하고 동 안 구조에 같은 규칙을 적용.
python stage2_write.py out/1_1단계.dxf out/s2_model.pkl out/s2_result.pkl out/1_2단계.dxf [--dx -1000000] [--dong-dir out/dong]
"""
import sys, os, argparse, pickle, time, math
import numpy as np
import ezdxf
from shapely.geometry import LineString, Polygon
from shapely.strtree import STRtree
import stage2_engine as E

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("model"); ap.add_argument("result"); ap.add_argument("out")
ap.add_argument("--dx", type=float, default=-1000000.0)
ap.add_argument("--dong-dir", default="out/dong")
ap.add_argument("--gw-x", type=float, default=400.0, help="X방향 거더 폭")
ap.add_argument("--gw-y", type=float, default=500.0, help="Y방향 거더 폭")
ap.add_argument("--bw", type=float, default=400.0, help="보 폭")
a = ap.parse_args()

L_G, L_B, L_LOW, L_DONG = "GIRDER", "BEAM", "----- (구조) 하부 골조", "----- (구조) 동 구역"
M = pickle.load(open(a.model, "rb")); FY, H, model = M["FY"], M["H"], M["model"]
RES = pickle.load(open(a.result, "rb")); result = RES["result"]; P = RES["P"]

t0 = time.time()
doc = ezdxf.readfile(a.src)
msp = doc.modelspace()
print(f"loaded {time.time()-t0:.0f}s")
if "HIDD" not in doc.linetypes:
    doc.linetypes.add("HIDD", pattern=[1.5, 1.0, -0.5])
for name, color, lt in ((L_G, 3, "HIDD"), (L_B, 4, "HIDD"), (L_LOW, 6, "HIDD"), (L_DONG, 5, "Continuous")):
    if name in doc.layers:
        ly = doc.layers.get(name); ly.color = color; ly.dxf.linetype = lt; ly.on()
    else:
        doc.layers.add(name, color=color, linetype=lt)


def unit(v):
    n = np.linalg.norm(v); return v / n if n else v


def trim_to_faces(a_pt, b_pt, obstacles_tree, obstacles, pad=0.0):
    """선분 a→b 의 양 끝을 장애물(기둥 폴리곤/거더 면선) 밖으로 자름: 끝점이 장애물 안이면 첫 교차점까지"""
    ls = LineString([tuple(a_pt), tuple(b_pt)])
    for idx in obstacles_tree.query(ls):
        ob = obstacles[idx]
        if ob.geom_type == "Polygon":
            if ob.contains(shapely_point(a_pt)):
                inter = ls.intersection(ob.exterior)
                a_pt = nearest_point(inter, a_pt, b_pt)
            if ob.contains(shapely_point(b_pt)):
                inter = ls.intersection(ob.exterior)
                b_pt = nearest_point(inter, b_pt, a_pt)
    return a_pt, b_pt


from shapely.geometry import Point as shapely_point


def nearest_point(inter, start, other):
    pts = []
    if inter.is_empty:
        return start
    geoms = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
    for q in geoms:
        if q.geom_type == "Point":
            pts.append(np.array([q.x, q.y]))
    if not pts:
        return start
    d = unit(np.array(other) - np.array(start))
    # start 에서 other 방향으로 가장 먼 교차점(장애물을 벗어나는 점)
    return max(pts, key=lambda p: np.dot(p - np.array(start), d))


def double_lines(layout, segs, width, layer, col_polys, col_tree, shift):
    """중심선 → 폭 width 의 2중선. 끝은 기둥 면에서 자름."""
    n_added = 0
    for s in segs:
        a_pt = np.array(s[:2]); b_pt = np.array(s[2:])
        d = unit(b_pt - a_pt)
        if not np.isfinite(d).all() or np.linalg.norm(b_pt - a_pt) < 1:
            continue
        nrm = np.array([-d[1], d[0]])
        for sgn in (1, -1):
            o = nrm * (width / 2) * sgn
            p1, p2 = a_pt + o, b_pt + o
            p1, p2 = trim_to_faces(p1, p2, col_tree, col_polys)
            if np.linalg.norm(p2 - p1) < 1:
                continue
            layout.add_line((p1[0], p1[1] + shift), (p2[0], p2[1] + shift), dxfattribs={"layer": layer})
            n_added += 1
    return n_added


def is_xish(s):
    ang = abs(math.degrees(math.atan2(s[3] - s[1], s[2] - s[0]))) % 180
    return ang < 45 or ang > 135


def add_support_overlay(layout, k, shift):
    """지지층(k) 기둥·벽을 하부 골조 레이어로"""
    m = model[k]
    n = 0
    for c in m["cols"]:
        pts = [(p[0], p[1] + shift) for p in c["poly"]]
        layout.add_lwpolyline(pts, close=True, dxfattribs={"layer": L_LOW}); n += 1
    for s in m["con"]:
        layout.add_line((s[0], s[1] + shift), (s[2], s[3] + shift), dxfattribs={"layer": L_LOW}); n += 1
    return n


total = {"girder": 0, "beam": 0}
for N, R in sorted(result.items()):
    k = R["support"]; sh = R["shift"]
    G = E.to_segs(R["girders"]); B = E.to_segs(R["beams"])  # 지지층 좌표
    col_polys = [Polygon([tuple(v) for v in c["poly"]]) for c in model[k]["cols"]]
    col_tree = STRtree(col_polys)
    if N >= 1:
        bname = f"B{N}_골조"
        blk = doc.blocks[bname]
        draw_shift = sh
    else:
        bname = "1F_골조"
        if bname in doc.blocks:
            doc.blocks.delete_block(bname, safe=False)
        blk = doc.blocks.new(name=bname)
        draw_shift = H  # B1 띠 위에 배치
        ins = msp.add_blockref(bname, (a.dx, 0.0), dxfattribs={"layer": "----- (구조) 골조"})
        g = doc.groups.new(name="GRP_1F_골조"); g.extend([ins])
    n_low = add_support_overlay(blk, k, draw_shift)
    ng = 0
    for s in G:
        w = a.gw_x if is_xish(s) else a.gw_y
        ng += double_lines(blk, [s], w, L_G, col_polys, col_tree, draw_shift)
    nb = double_lines(blk, B, a.bw, L_B, col_polys, col_tree, draw_shift)
    # 동 구역 외곽
    for i, dg in enumerate(model[k].get("dong", [])):
        pts = [(x, y + draw_shift) for x, y in dg.exterior.coords]
        blk.add_lwpolyline(pts, close=True, dxfattribs={"layer": L_DONG})
    total["girder"] += ng; total["beam"] += nb
    print(f"{'B'+str(N) if N else '1F'} ← 지지층 B{k}: 거더 {len(G)}개({ng}선) 보 {len(B)}개({nb}선) 하부골조 {n_low}")

# 동(아파트) 별도 파일: 지지층별 동 폴리곤 안 구조만 추출 + 같은 규칙으로 거더/보
os.makedirs(a.dong_dir, exist_ok=True)
Pd = E.Params()
for key, val in P.items():
    setattr(Pd, key, val)
Pd.EXCLUDE_DONG = False
n_files = 0
for k in sorted(model):
    m = model[k]
    for i, dg in enumerate(m.get("dong", [])):
        import shapely
        cols = [c for c in m["cols"] if dg.contains(shapely.points(c["cx"], c["cy"]))]
        mid = (m["con"][:, :2] + m["con"][:, 2:]) / 2
        inside = shapely.contains_xy(dg, mid[:, 0], mid[:, 1])
        con = m["con"][inside]
        if len(con) == 0 and not cols:
            continue
        d2 = ezdxf.new("R2010")
        for name, color in (("----- (구조) 골조", 2), (L_G, 3), (L_B, 4), (L_DONG, 5)):
            d2.layers.add(name, color=color)
        ms = d2.modelspace()
        for s in con:
            ms.add_line((s[0], s[1]), (s[2], s[3]), dxfattribs={"layer": "----- (구조) 골조"})
        for c in cols:
            ms.add_lwpolyline([tuple(p) for p in c["poly"]], close=True, dxfattribs={"layer": "----- (구조) 골조"})
        ms.add_lwpolyline(list(dg.exterior.coords), close=True, dxfattribs={"layer": L_DONG})
        if cols:
            th = m["con_th"][inside]
            gd, bd = E.generate(cols, con, Pd, dong=None, con_th=th)
            cp = [Polygon([tuple(v) for v in c["poly"]]) for c in cols]; ct = STRtree(cp)
            for s in E.to_segs(gd):
                double_lines(ms, [s], a.gw_x if is_xish(s) else a.gw_y, L_G, cp, ct, 0.0)
            double_lines(ms, E.to_segs(bd), a.bw, L_B, cp, ct, 0.0)
        fn = os.path.join(a.dong_dir, f"동_B{k}_{i+1:02d}.dxf")
        d2.saveas(fn); n_files += 1
print(f"동 분리 파일 {n_files}개 → {a.dong_dir}")

try:
    od = doc.materials.object_dict
    for kk in [kk for kk, v in list(od.items()) if isinstance(v, str)]:
        od.remove(kk)
except Exception as ex:
    print("materials 정리 생략:", ex)
doc.saveas(a.out)
print(f"saved {a.out}  거더선 {total['girder']} 보선 {total['beam']}  {time.time()-t0:.0f}s")
