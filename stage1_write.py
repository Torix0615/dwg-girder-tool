"""1단계 DXF 출력: 원본 DXF 를 열어 층별 골조 블록(골조/중심선/OPEN)을 좌측에 삽입·그룹화, 그 외 레이어 숨김.
python stage1_write.py data/1.dxf out/s1_cand.pkl out/1_1단계.dxf [--dx -1000000] [--golf-layers CON,COL] [--cen-layers CEN,CEN-1,CEN-PARK]
"""
import sys, argparse, pickle, time, math
import ezdxf
from ezdxf.math import Vec2

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("cand"); ap.add_argument("out")
ap.add_argument("--dx", type=float, default=-1000000.0)
ap.add_argument("--golf-layers", default="CON,COL")
ap.add_argument("--cen-layers", default="CEN,CEN-1,CEN-PARK")
ap.add_argument("--no-hide", action="store_true")
a = ap.parse_args()

L_GOLF, L_CEN, L_OPEN = "----- (구조) 골조", "----- (구조) 중심선", "----- (구조) OPEN"
C = pickle.load(open(a.cand, "rb"))  # 내 스크립트가 만든 피클(신뢰)
cand = C["cand"]
t0 = time.time()
doc = ezdxf.readfile(a.src)
msp = doc.modelspace()
print(f"loaded {time.time()-t0:.0f}s")

if "CEN" not in doc.linetypes:
    doc.linetypes.add("CEN", pattern=[2.0, 1.25, -0.25, 0.25, -0.25])
for name, color, lt in ((L_GOLF, 2, "Continuous"), (L_CEN, 1, "CEN"), (L_OPEN, 8, "Continuous")):
    if name in doc.layers:
        ly = doc.layers.get(name); ly.color = color; ly.dxf.linetype = lt
    else:
        doc.layers.add(name, color=color, linetype=lt)


def add_prims(layout, prims, layer):
    n = 0
    for p in prims:
        k = p["kind"]
        attr = {"layer": layer}
        if k == "LINE":
            layout.add_line((p["x1"], p["y1"]), (p["x2"], p["y2"]), dxfattribs=attr)
        elif k == "POLY":
            layout.add_lwpolyline([(q[0], q[1], 0, 0, q[2]) for q in p["pts"]], format="xyseb", close=p.get("closed", False), dxfattribs=attr)
        elif k == "ARC":
            layout.add_arc((p["cx"], p["cy"]), p["r"], p["a1"], p["a2"], dxfattribs=attr)
        elif k == "CIRCLE":
            layout.add_circle((p["cx"], p["cy"]), p["r"], dxfattribs=attr)
        elif k == "TEXT":
            layout.add_text(p["s"], height=p["h"], rotation=p.get("rot", 0), dxfattribs={**attr}).set_placement((p["x"], p["y"]))
        else:
            continue
        n += 1
    return n


golf_l = set(a.golf_layers.split(",")); cen_l = set(a.cen_layers.split(","))
total = 0
for n in sorted(cand):
    bname = f"B{n}_골조"
    if bname in doc.blocks:
        doc.blocks.delete_block(bname, safe=False)
    blk = doc.blocks.new(name=bname)
    c = cand[n]
    k1 = add_prims(blk, [p for p in c["golf"] if p["layer"] in golf_l], L_GOLF)
    k2 = add_prims(blk, [p for p in c["cen"] if p["layer"] in cen_l], L_CEN)
    k3 = add_prims(blk, c["open"] + c["open_text"], L_OPEN)
    ins = msp.add_blockref(bname, (a.dx, 0.0), dxfattribs={"layer": L_GOLF})
    gname = f"GRP_B{n}_골조"
    if gname in doc.groups:
        doc.groups.delete(gname)
    g = doc.groups.new(name=gname)
    g.extend([ins])
    total += k1 + k2 + k3
    print(f"B{n}: 골조 {k1} 중심선 {k2} OPEN {k3} → 블록 {bname} @ ({a.dx:.0f}, 0), 그룹 {gname}")

if not a.no_hide:
    keep = {L_GOLF, L_CEN, L_OPEN}
    for ly in doc.layers:
        if ly.dxf.name not in keep:
            ly.off()
    print("기타 레이어 숨김(off):", len(doc.layers) - len(keep))

# LibreDWG 변환 DXF 의 ACAD_MATERIAL 미해결 핸들 제거(저장 실패 방지)
try:
    od = doc.materials.object_dict
    bad = [k for k, v in list(od.items()) if isinstance(v, str)]
    for k in bad:
        od.remove(k)
    if bad:
        print("materials 미해결 항목 제거:", len(bad))
except Exception as ex:
    print("materials 정리 생략:", ex)

doc.saveas(a.out)
print(f"saved {a.out}  entities={total}  {time.time()-t0:.0f}s")
