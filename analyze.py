"""DXF 구조 분석: 레이어(색)·모델공간 엔티티(레이어/타입별)·INSERT 블록·범위를 요약 JSON으로 저장.
사용: python -I analyze.py <dxf> <out.json>
"""
import sys, json, time, collections
import ezdxf

src, out = sys.argv[1], sys.argv[2]
t0 = time.time()
doc = ezdxf.readfile(src)
msp = doc.modelspace()
print(f"loaded {src} in {time.time()-t0:.1f}s, dxfversion={doc.dxfversion}", flush=True)

layers = {}
for ly in doc.layers:
    layers[ly.dxf.name] = {"color": ly.dxf.color, "on": ly.is_on(), "frozen": ly.is_frozen(), "ltype": ly.dxf.linetype}

def ext(e):
    try:
        if e.dxftype() == "LINE":
            return [e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y]
        if e.dxftype() in ("LWPOLYLINE",):
            pts = list(e.get_points("xy"))
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            return [min(xs), min(ys), max(xs), max(ys)]
        if e.dxftype() == "INSERT":
            return [e.dxf.insert.x, e.dxf.insert.y]
        if e.dxftype() in ("TEXT", "MTEXT"):
            return [e.dxf.insert.x, e.dxf.insert.y]
    except Exception:
        return None
    return None

cnt = collections.Counter()
per_layer_bbox = {}
inserts = collections.Counter()
insert_list = []
texts = []
for e in msp:
    t = e.dxftype()
    ly = e.dxf.layer
    cnt[(ly, t)] += 1
    b = ext(e)
    if b:
        xs = b[0::2]; ys = b[1::2]
        bb = per_layer_bbox.setdefault(ly, [1e18, 1e18, -1e18, -1e18])
        bb[0] = min(bb[0], *xs); bb[1] = min(bb[1], *ys); bb[2] = max(bb[2], *xs); bb[3] = max(bb[3], *ys)
    if t == "INSERT":
        inserts[e.dxf.name] += 1
        if len(insert_list) < 400:
            insert_list.append({"name": e.dxf.name, "layer": ly, "x": round(e.dxf.insert.x, 1), "y": round(e.dxf.insert.y, 1),
                                "sx": round(e.dxf.xscale, 3), "rot": round(e.dxf.rotation, 2)})
    if t in ("TEXT", "MTEXT"):
        s = e.dxf.text if t == "TEXT" else e.text
        if s and len(texts) < 3000:
            texts.append({"layer": ly, "x": round(e.dxf.insert.x, 1), "y": round(e.dxf.insert.y, 1), "h": round(e.dxf.char_height if t == "MTEXT" else e.dxf.height, 1), "s": s[:60]})

blocks = {}
for b in doc.blocks:
    if b.name.startswith("*"):
        continue
    c = collections.Counter()
    n = 0
    for e in b:
        c[(e.dxf.layer, e.dxftype())] += 1
        n += 1
    blocks[b.name] = {"n": n, "top": [[k[0], k[1], v] for k, v in c.most_common(12)]}

groups = {}
try:
    for name, g in doc.groups:
        groups[name] = len(list(g))
except Exception as ex:
    groups["_err"] = str(ex)

summary = {
    "file": src, "version": doc.dxfversion, "load_s": round(time.time() - t0, 1),
    "layers": layers,
    "msp_counts": [[k[0], k[1], v] for k, v in cnt.most_common()],
    "layer_bbox": {k: [round(x, 1) for x in v] for k, v in per_layer_bbox.items()},
    "inserts": inserts.most_common(),
    "insert_samples": insert_list,
    "texts": texts,
    "blocks": blocks,
    "groups": groups,
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)
print(f"done {out} in {time.time()-t0:.1f}s; msp entities={sum(cnt.values())} layers={len(layers)} blocks={len(blocks)} groups={len(groups)}")
