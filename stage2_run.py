"""2단계 실행+비교: 도면 B1~B5(지지층 = 아래층) + 1F(지지층 B1) 거더·보 생성 → 참조 중심선과 일치율.
python stage2_run.py out/s2_model.pkl out/s2_ref.pkl out/s2_result.pkl [--ang 8 --split 6000 --lmax 14000 --no-t --no-wall] [--render N] [--report f]
"""
import sys, argparse, pickle, time
import numpy as np
from geom import match_metrics
import stage2_engine as E

ap = argparse.ArgumentParser()
ap.add_argument("model"); ap.add_argument("ref"); ap.add_argument("out")
ap.add_argument("--ang", type=float); ap.add_argument("--split", type=float); ap.add_argument("--lmax", type=float)
ap.add_argument("--perp", type=float); ap.add_argument("--wallcross", type=float); ap.add_argument("--wallminlen", type=float)
ap.add_argument("--no-t", action="store_true"); ap.add_argument("--no-wall", action="store_true"); ap.add_argument("--keep-dong", action="store_true")
ap.add_argument("--tol", type=float, default=100.0, help="중심선 길이 일치 허용 거리")
ap.add_argument("--wallth", type=float); ap.add_argument("--single", type=float)
ap.add_argument("--dmin", type=float); ap.add_argument("--dtwo", type=float)
ap.add_argument("--bwall", type=float); ap.add_argument("--bsingle", type=float)
ap.add_argument("--render", type=int, nargs="*")
ap.add_argument("--report")
ap.add_argument("--floors", default="1,2,3,4,5,0")
a = ap.parse_args()

M = pickle.load(open(a.model, "rb")); FY, model = M["FY"], M["model"]
ref = pickle.load(open(a.ref, "rb"))
P = E.Params()
if a.ang: P.ANG = a.ang
if a.split: P.SPLIT = a.split
if a.lmax: P.LMAX = a.lmax
if a.perp: P.PERP_MIN = a.perp
if a.wallcross: P.WALL_CROSS_DEG = a.wallcross
if a.wallminlen: P.WALL_MIN_LEN = a.wallminlen
if a.no_t: P.T_JUNCTION = False
if a.no_wall: P.WALL_GIRDER = False
if a.keep_dong: P.EXCLUDE_DONG = False
if a.wallth is not None: P.WALL_TH_MIN = a.wallth
if a.dmin is not None: P.D_MIN = a.dmin
if a.bwall is not None: P.BEAM_WALL_TH = a.bwall
if a.bsingle is not None: P.BEAM_WALL_SINGLE = a.bsingle
if a.dtwo is not None: P.D_TWO = a.dtwo
if a.single is not None: P.WALL_SINGLE_MINLEN = a.single

lines = []
def out(s=""):
    print(s, flush=True); lines.append(s)

result = {}
summary = []
for N in [int(x) for x in a.floors.split(",")]:
    k = N + 1 if N >= 1 else 1
    sh = (FY[N] - FY[k]) if N >= 1 else 0.0
    t0 = time.time()
    girders, beams = E.generate(model[k]["cols"], model[k]["con"], P, dong=model[k].get("dong"), con_th=model[k].get("con_th"))
    G = E.to_segs(girders) + np.array([0, sh, 0, sh]); B = E.to_segs(beams) + np.array([0, sh, 0, sh])
    kinds = {}
    for g in girders:
        kinds[g["kb"]] = kinds.get(g["kb"], 0) + 1
    r = ref[N]
    mg = match_metrics(r["girder_cl"], G, tol=a.tol, step=50, cover_tol=a.tol)
    mb = match_metrics(r["beam_cl"], B, tol=a.tol, step=50, cover_tol=a.tol)
    name = f"B{N}" if N else "1F"
    out(f"===== 도면 {name} (지지층 B{k}, 기둥 {len(model[k]['cols'])}) 생성 {time.time()-t0:.1f}s  거더 {len(girders)} {kinds}  보 {len(beams)}")
    out(f"  거더 중심선: 참조 {mg['ref_n']}개/{mg['ref_len']/1000:.0f}m 내것 {mg['my_n']}개/{mg['my_len']/1000:.0f}m  길이재현 {mg['len_recall']:.1f}% 정밀 {mg['len_prec']:.1f}%  F1 {mg['f1']:.1f}%")
    out(f"  보   중심선: 참조 {mb['ref_n']}개/{mb['ref_len']/1000:.0f}m 내것 {mb['my_n']}개/{mb['my_len']/1000:.0f}m  길이재현 {mb['len_recall']:.1f}% 정밀 {mb['len_prec']:.1f}%  F1 {mb['f1']:.1f}%")
    result[N] = {"girders": girders, "beams": beams, "shift": sh, "support": k, "G": G, "B": B, "mg": mg, "mb": mb}
    summary.append((name, mg, mb))
    if a.render and N in a.render:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
        fig, ax = plt.subplots(figsize=(30, 20), dpi=100)
        con = model[k]["con"] + np.array([0, sh, 0, sh])
        def draw(S, c, lw):
            if len(S): ax.add_collection(LineCollection(S.reshape(-1, 2, 2), colors=c, linewidths=lw))
        draw(con, "#bbbbbb", 0.3)
        for c in model[k]["cols"]:
            p = c["poly"] + np.array([0, sh]); ax.fill(p[:, 0], p[:, 1], color="#000000")
        draw(r["girder_cl"], "#00bb00", 2.0); draw(r["beam_cl"], "#66ccff", 1.5)
        draw(G, "#ff0000", 0.8); draw(B, "#ff8800", 0.7)
        allx = np.concatenate([r["girder_cl"][:, [0, 2]].ravel(), G[:, [0, 2]].ravel()]); ally = np.concatenate([r["girder_cl"][:, [1, 3]].ravel(), G[:, [1, 3]].ravel()])
        ax.set_xlim(allx.min() - 5000, allx.max() + 5000); ax.set_ylim(ally.min() - 5000, ally.max() + 5000); ax.set_aspect("equal"); ax.axis("off")
        fig.savefig(f"out/s2_view_{name}.png", bbox_inches="tight"); plt.close(fig)
        out(f"  렌더: out/s2_view_{name}.png (참조=초록/하늘, 내것=빨강/주황)")

out("===== 요약(중심선 길이 기준, 허용 %.0fmm)" % a.tol)
out("도면  거더재현 거더정밀 거더F1 | 보재현 보정밀 보F1")
for name, mg, mb in summary:
    out(f"{name:4s} {mg['len_recall']:7.1f} {mg['len_prec']:7.1f} {mg['f1']:6.1f} | {mb['len_recall']:6.1f} {mb['len_prec']:6.1f} {mb['f1']:5.1f}")
out(f"평균 {np.mean([s[1]['len_recall'] for s in summary]):7.1f} {np.mean([s[1]['len_prec'] for s in summary]):7.1f} {np.mean([s[1]['f1'] for s in summary]):6.1f} | "
    f"{np.mean([s[2]['len_recall'] for s in summary]):6.1f} {np.mean([s[2]['len_prec'] for s in summary]):6.1f} {np.mean([s[2]['f1'] for s in summary]):5.1f}")
pickle.dump({"result": result, "params": vars(P) if hasattr(P, "__dict__") else {}, "P": {k: getattr(P, k) for k in dir(P) if k.isupper()}}, open(a.out, "wb"), protocol=5)
if a.report:
    open(a.report, "w", encoding="utf-8").write("\n".join(lines))
