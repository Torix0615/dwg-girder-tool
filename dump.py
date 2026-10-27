"""DXF → 분석용 피클.
python -P dump.py <dxf> <out.pkl> [--msp] [--blocks 정규식] [--msp-layers 정규식] [--keep 정규식]
 --msp            : 모델공간 전체를 재귀 전개
 --blocks RE      : 이름이 RE 에 맞는 블록 정의를 (원점 기준) 전개해 저장
 --msp-layers RE  : 모델공간에서 레이어가 RE 에 맞는 엔티티만 (전개 없이) 저장
 --keep RE        : 전개하지 않고 INSERT 로 남길 블록 이름
항상 저장: 레이어색, 모델공간 INSERT 전체 목록(name,x,y,sx,sy,rot,layer)
"""
import sys, re, pickle, time, argparse
import ezdxf
from dxfio import flatten, layer_colors

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--msp", action="store_true")
ap.add_argument("--blocks"); ap.add_argument("--msp-layers"); ap.add_argument("--keep")
a = ap.parse_args()

t0 = time.time()
doc = ezdxf.readfile(a.src)
msp = doc.modelspace()
lc = layer_colors(doc)
print(f"loaded {time.time()-t0:.0f}s", flush=True)
keep = (lambda n: re.search(a.keep, n) is not None) if a.keep else None

inserts = []
for e in msp.query("INSERT"):
    inserts.append({"name": e.dxf.name, "x": e.dxf.insert.x, "y": e.dxf.insert.y, "sx": e.dxf.xscale, "sy": e.dxf.yscale,
                    "rot": e.dxf.rotation, "layer": e.dxf.layer})
res = {"file": a.src, "lcolors": lc, "inserts": inserts, "blocks": {}, "msp": None, "msp_layers": None}

if a.msp:
    out = []
    flatten(doc, msp, out, keep_insert=keep)
    res["msp"] = out
    print(f"msp flattened: {len(out)} prims {time.time()-t0:.0f}s", flush=True)
if a.blocks:
    for b in doc.blocks:
        if b.name.startswith("*") or not re.search(a.blocks, b.name):
            continue
        out = []
        flatten(doc, b, out, keep_insert=keep)
        res["blocks"][b.name] = out
        print(f"block {b.name}: {len(out)} prims", flush=True)
if a.msp_layers:
    out = []
    ents = [e for e in msp if re.search(a.msp_layers, e.dxf.layer)]
    flatten(doc, ents, out, keep_insert=lambda n: True)
    res["msp_layers"] = out
    print(f"msp layer prims: {len(out)}", flush=True)

with open(a.out, "wb") as f:
    pickle.dump(res, f, protocol=5)
print(f"saved {a.out} {time.time()-t0:.0f}s")
