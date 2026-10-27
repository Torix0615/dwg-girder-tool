"""불일치 렌더: python stage2_diff.py N [x0 x1 y0 y1]  → out/s2_diff_B{N}_{all|zoom}.png
참조만(초록=거더, 파랑=보) / 내것만(빨강=거더, 주황=보), 연한색=일치"""
import sys, pickle, numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from scipy.spatial import cKDTree
from geom import sample_points

N = int(sys.argv[1])
M = pickle.load(open("out/s2_model.pkl", "rb")); FY = M["FY"]; model = M["model"]
ref = pickle.load(open("out/s2_ref.pkl", "rb")); res = pickle.load(open("out/s2_result.pkl", "rb"))["result"]
k = N + 1 if N else 1; sh = (FY[N] - FY[k]) if N else 0.0; r = ref[N]; R = res[N]


def unmatched(A, Bs, tol=100):
    if len(Bs) == 0:
        return A
    t = cKDTree(sample_points(Bs, 50)); out = []
    for s in A:
        p = sample_points(s[None, :], 50); d, _ = t.query(p, distance_upper_bound=tol)
        if np.isfinite(d).mean() < 0.5:
            out.append(s)
    return np.array(out) if out else np.zeros((0, 4))


rg = unmatched(r["girder_cl"], R["G"]); mg = unmatched(R["G"], r["girder_cl"])
rb = unmatched(r["beam_cl"], R["B"]); mb = unmatched(R["B"], r["beam_cl"])
print(f"B{N}: 참조만 거더 {len(rg)}/{len(r['girder_cl'])} 보 {len(rb)}/{len(r['beam_cl'])} | 내것만 거더 {len(mg)}/{len(R['G'])} 보 {len(mb)}/{len(R['B'])}")
tag = "all" if len(sys.argv) < 6 else "zoom"
fig, ax = plt.subplots(figsize=(26, 18), dpi=100)
con = model[k]["con"] + np.array([0, sh, 0, sh])
def draw(S, c, lw):
    if len(S): ax.add_collection(LineCollection(S.reshape(-1, 2, 2), colors=c, linewidths=lw))
draw(con, "#cccccc", 0.4)
for c in model[k]["cols"]:
    p = c["poly"] + np.array([0, sh]); ax.fill(p[:, 0], p[:, 1], color="#000000")
for g in model[k].get("dong", []):
    x, y = g.exterior.xy; ax.plot(np.array(x), np.array(y) + sh, color="#aa00aa", lw=1.0, ls="--")
draw(r["girder_cl"], "#bbddbb", 0.8); draw(r["beam_cl"], "#bbddff", 0.8)
draw(rg, "#00aa00", 1.6); draw(mg, "#ff0000", 1.6); draw(rb, "#0055ff", 1.2); draw(mb, "#ff8800", 1.2)
if tag == "all":
    allx = r["girder_cl"][:, [0, 2]].ravel(); ally = r["girder_cl"][:, [1, 3]].ravel()
    x0, x1, y0, y1 = allx.min() - 5000, allx.max() + 5000, ally.min() - 5000, ally.max() + 5000
else:
    x0, x1, y0, y1 = map(float, sys.argv[2:6])
ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.axis("off")
fig.savefig(f"out/s2_diff_B{N}_{tag}.png", bbox_inches="tight"); plt.close(fig)
