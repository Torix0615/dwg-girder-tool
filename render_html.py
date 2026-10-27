"""최종 DXF 의 층별 블록을 PNG 로 렌더하고 HTML 2개(1단계 골조 추출 / 2단계 거더·보)로 묶는다.
python render_html.py out/최종.dxf out/html
"""
import sys, os, io, base64, time, json
import numpy as np
import ezdxf
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt; plt.rcParams["font.family"] = "Malgun Gothic"
from matplotlib.collections import LineCollection
from geom import arc_points, bulge_points

src, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
t0 = time.time()
doc = ezdxf.readfile(src)
print(f"loaded {time.time()-t0:.0f}s")

L_GOLF, L_CEN, L_OPEN = "----- (구조) 골조", "----- (구조) 중심선", "----- (구조) OPEN"
L_G, L_B, L_LOW, L_DONG = "GIRDER", "BEAM", "----- (구조) 하부 골조", "----- (구조) 동 구역"
STYLE1 = {L_GOLF: ("#8a6d00", 1.8), L_CEN: ("#c00000", 0.9), L_OPEN: ("#303030", 1.2)}
STYLE2 = {L_GOLF: ("#d8c878", 0.5), L_LOW: ("#b060b0", 0.8), L_DONG: ("#2040e0", 1.6), L_G: ("#107010", 2.0), L_B: ("#0060e0", 1.6)}


def block_segments(blk, layers):
    segs = {ly: [] for ly in layers}; texts = []
    for e in blk:
        ly = e.dxf.layer
        if ly not in segs:
            continue
        t = e.dxftype()
        if t == "LINE":
            segs[ly].append([e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y])
        elif t == "LWPOLYLINE":
            pts = list(e.get_points("xyb")); n = len(pts)
            rng = range(n) if e.closed else range(n - 1)
            for i in rng:
                a = pts[i]; b = pts[(i + 1) % n]
                if abs(a[2]) > 1e-9:
                    bp = bulge_points(a, b)
                    for j in range(len(bp) - 1):
                        segs[ly].append([bp[j][0], bp[j][1], bp[j + 1][0], bp[j + 1][1]])
                else:
                    segs[ly].append([a[0], a[1], b[0], b[1]])
        elif t == "ARC":
            ap = arc_points(e.dxf.center.x, e.dxf.center.y, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle)
            for j in range(len(ap) - 1):
                segs[ly].append([ap[j][0], ap[j][1], ap[j + 1][0], ap[j + 1][1]])
        elif t == "CIRCLE":
            ap = arc_points(e.dxf.center.x, e.dxf.center.y, e.dxf.radius, 0, 360, 16)
            for j in range(len(ap) - 1):
                segs[ly].append([ap[j][0], ap[j][1], ap[j + 1][0], ap[j + 1][1]])
        elif t == "TEXT":
            texts.append((e.dxf.insert.x, e.dxf.insert.y, e.dxf.text, ly))
    return {k: (np.array(v) if v else np.zeros((0, 4))) for k, v in segs.items()}, texts


def render(segs, style, width_px=6400, texts=None, bbox=None):
    allx = np.concatenate([s[:, [0, 2]].ravel() for s in segs.values() if len(s)] or [np.zeros(1)])
    ally = np.concatenate([s[:, [1, 3]].ravel() for s in segs.values() if len(s)] or [np.zeros(1)])
    if bbox is None:
        x0, x1, y0, y1 = allx.min(), allx.max(), ally.min(), ally.max()
    else:
        x0, y0, x1, y1 = bbox
    pad = 0.01 * max(x1 - x0, y1 - y0)
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad
    w = x1 - x0; h = y1 - y0
    dpi = 100
    fig = plt.figure(figsize=(width_px / dpi, width_px * h / w / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    for ly, (c, lw) in style.items():
        S = segs.get(ly)
        if S is not None and len(S):
            ax.add_collection(LineCollection(S.reshape(-1, 2, 2), colors=c, linewidths=lw))
    if texts:
        for x, y, s, ly in texts:
            if ly == L_OPEN:
                ax.text(x, y, s, fontsize=4, color="#555555")
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.axis("off")
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=dpi, facecolor="white"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode(), (x0, y0, x1, y1)


FLOORS = ["B1", "B2", "B3", "B4", "B5", "B6"]
pages = {"1": [], "2": []}
counts = {}
for fl in FLOORS:
    blk = doc.blocks[f"{fl}_골조"]
    segs, texts = block_segments(blk, [L_GOLF, L_CEN, L_OPEN, L_LOW, L_DONG, L_G, L_B])
    counts[fl] = {k: len(v) for k, v in segs.items()}
    g = segs[L_GOLF]
    bbg = (g[:, [0, 2]].min(), g[:, [1, 3]].min(), g[:, [0, 2]].max(), g[:, [1, 3]].max())
    png1, bb = render({k: segs[k] for k in STYLE1}, STYLE1, texts=texts, bbox=bbg)
    pages["1"].append((fl, png1, bb))
    if len(segs[L_G]):
        png2, bb2 = render({k: segs[k] for k in STYLE2}, STYLE2, bbox=bb)
        pages["2"].append((fl, png2, bb2))
    print(fl, counts[fl], f"{time.time()-t0:.0f}s", flush=True)
if "1F_골조" in doc.blocks:
    segs, _ = block_segments(doc.blocks["1F_골조"], [L_LOW, L_DONG, L_G, L_B])
    g = segs[L_LOW]
    png2, bb2 = render(segs, STYLE2, bbox=(g[:, [0, 2]].min(), g[:, [1, 3]].min(), g[:, [0, 2]].max(), g[:, [1, 3]].max()))
    pages["2"].insert(0, ("1F", png2, bb2))
    counts["1F"] = {k: len(v) for k, v in segs.items()}

CSS = """
*{box-sizing:border-box} body{margin:0;font-family:'Malgun Gothic',sans-serif;background:#f3f4f6;color:#222}
header{position:sticky;top:0;background:#1f2937;color:#fff;padding:10px 16px;z-index:5;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header h1{font-size:17px;margin:0 12px 0 0} header a{color:#fff;text-decoration:none;background:#374151;padding:4px 10px;border-radius:4px;font-size:14px}
header a:hover{background:#4b5563} .legend{margin-left:auto;font-size:12px;display:flex;gap:10px;flex-wrap:wrap}
.legend span{display:inline-flex;align-items:center;gap:4px} .legend i{display:inline-block;width:18px;height:3px}
section{padding:14px 16px 6px} section h2{font-size:16px;margin:4px 0 8px} .meta{font-size:12px;color:#555;margin-bottom:6px}
.wrap{background:#fff;border:1px solid #d1d5db;overflow:auto;max-height:88vh;cursor:zoom-in}
.wrap img{display:block;width:100%;height:auto} .wrap.zoom{cursor:zoom-out} .wrap.zoom img{width:auto;max-width:none}
.note{font-size:12px;color:#666;padding:0 16px 20px}
"""
JS = "document.querySelectorAll('.wrap').forEach(w=>w.addEventListener('click',()=>w.classList.toggle('zoom')));"


def build(title, legend, items, note, fn, layers):
    nav = "".join(f'<a href="#{fl}">{fl}</a>' for fl, _, _ in items)
    leg = "".join(f'<span><i style="background:{c}"></i>{n}</span>' for n, c in legend)
    body = ""
    for fl, png, bb in items:
        c = counts.get(fl, {})
        meta = " · ".join(f"{k.replace('----- (구조) ', '')} {v:,}" for k, v in c.items() if v and k in layers)
        body += (f'<section id="{fl}"><h2>{fl}</h2><div class="meta">선분 수: {meta} · 범위 x {bb[0]:,.0f}~{bb[2]:,.0f}, y {bb[1]:,.0f}~{bb[3]:,.0f} (mm)</div>'
                 f'<div class="wrap"><img src="data:image/png;base64,{png}" alt="{fl}"></div></section>')
    html = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>'
            f'<header><h1>{title}</h1>{nav}<div class="legend">{leg}</div></header>{body}<div class="note">{note}</div><script>{JS}</script></body></html>')
    open(fn, "w", encoding="utf-8").write(html)
    print("wrote", fn, f"{os.path.getsize(fn)/1e6:.1f} MB")


build("1단계 골조 추출 — 층별 전체 도면", [("골조(벽체·기둥)", "#8a6d00"), ("중심선", "#c00000"), ("OPEN", "#303030")], pages["1"],
      "원본 2A-04-001 지하주차장 평면도에서 노랑(CON·COL) 골조, 붉은 중심선(CEN·CEN-1·CEN-PARK), OPEN 레이어만 추출. 이미지를 클릭하면 원본 크기(스크롤)로 전환. 2026-10-27 생성.",
      os.path.join(outdir, "1단계_골조추출_층별도면.html"), list(STYLE1))
build("2단계 거더·보 — 층별 전체 도면", [("GIRDER", "#107010"), ("BEAM", "#0060e0"), ("하부 골조(아래층 기둥·벽)", "#b060b0"), ("동 구역", "#2040e0"), ("자기 층 골조", "#d8c878")], pages["2"],
      "N층 도면의 거더·보는 아래층(N+1) 기둥·벽 위에 그려짐(1F=B1 기둥, B6 없음). 거더 폭 X 400·Y 500, 보 폭 400 의 2중선. 이미지를 클릭하면 원본 크기(스크롤)로 전환. 2026-10-27 생성.",
      os.path.join(outdir, "2단계_거더보_층별도면.html"), [L_LOW, L_DONG, L_G, L_B])
print(f"done {time.time()-t0:.0f}s")
