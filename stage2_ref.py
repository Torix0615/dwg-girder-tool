"""참조 3번 파일(d3.pkl)의 거더·보를 도면(층)별로 나누고 원본 좌표(해당 층 띠)로 옮긴 뒤 2중선→중심선으로 변환.
python stage2_ref.py out/d3.pkl out/s2_model.pkl out/s2_ref.pkl
결과: ref[N] = {"girder_lines":(n,4), "beam_lines":(n,4), "girder_cl":(n,4), "beam_cl":(n,4), "off":(dx,dy)}  N=1..5, 그리고 N=0 → 1층 바닥(지1 b 열)
"""
import sys, pickle
import numpy as np
from scipy.spatial import cKDTree
from geom import to_segments, find_offset

d3 = pickle.load(open(sys.argv[1], "rb")); M = pickle.load(open(sys.argv[2], "rb"))
FY, model = M["FY"], M["model"]
ml = d3["msp_layers"]
# 도면 열: 왼쪽부터 지하 6, 지하 5, 지하4, 지하3, 지2, 지1, 지1 b (y≈8.5M 행)
COLS = {6: "지하 6", 5: "지하 5", 4: "지하4", 3: "지하3", 2: "지2", 1: "지1", 0: "지1 b"}
BBLK = {5: "지6 b", 4: "지5 b", 3: "지3 b", 2: "wl3 b", 1: "지2 b", 0: "지1 b"}  # 각 열의 하부 골조 블록
ins = {}
for i in d3["inserts"]:
    if i["x"] < 5e6 and 8.4e6 < i["y"] < 8.7e6:
        ins.setdefault(i["name"], []).append((i["x"], i["y"]))
xs = sorted((v[0][0], k) for k, v in ins.items() if k in COLS.values())


def col_of(x):
    name = None
    for x0, k in xs:
        if x >= x0 - 40000:
            name = k
    return name


cmp1 = pickle.load(open("out/s1_cand_cmp.pkl", "rb"))


def pair_centerlines(S):
    if len(S) == 0:
        return S
    d = S[:, 2:] - S[:, :2]; L = np.hypot(d[:, 0], d[:, 1]); u = d / np.maximum(L, 1e-9)[:, None]
    mid = (S[:, :2] + S[:, 2:]) / 2; t = cKDTree(mid)
    used = np.zeros(len(S), bool); out = []
    order = np.argsort(-L)
    for i in order:
        if used[i]:
            continue
        best = None
        for j in t.query_ball_point(mid[i], 1200):
            if j == i or used[j] or abs(np.dot(u[i], u[j])) < 0.995 or abs(L[i] - L[j]) > max(0.3 * L[i], 300):
                continue
            w = mid[j] - mid[i]; perp = abs(w[0] * u[i][1] - w[1] * u[i][0]); along = abs(np.dot(w, u[i]))
            if along > 0.5 * L[i] or perp < 100 or perp > 1100:
                continue
            if best is None or perp < best[0]:
                best = (perp, j)
        if best is None:
            out.append(S[i]); used[i] = True
            continue
        j = best[1]; used[i] = used[j] = True
        a1, b1 = S[i, :2], S[i, 2:]
        a2, b2 = S[j, :2], S[j, 2:]
        if np.dot(b1 - a1, b2 - a2) < 0:
            a2, b2 = b2, a2
        # 겹치는 구간만: 각 끝점을 선 i 방향으로 투영
        p = []
        for q in (a1, b1, a2, b2):
            p.append(np.dot(q - a1, u[i]))
        lo = max(min(p[0], p[1]), min(p[2], p[3])); hi = min(max(p[0], p[1]), max(p[2], p[3]))
        c0 = (a1 + a2) / 2
        n = np.array([-u[i][1], u[i][0]])
        base = a1 + n * (np.dot(c0 - a1, n))
        out.append(np.concatenate([base + u[i] * lo, base + u[i] * hi]))
    return np.array(out)


ref = {}
for N, nm in COLS.items():
    if N == 6:
        continue
    k = N + 1 if N >= 1 else 1
    sup = model[k]
    sh = FY[N] - FY[k] if N >= 1 else 0.0
    # 하부 골조 블록(지지층 골조) 로 오프셋 추정
    bname = BBLK[N]
    if N >= 1:
        wx, wy = ins[nm][0]
        dx, dy = -wx + cmp1[N]["dx"], -wy + cmp1[N]["dy"]; nx = ny = -1
    else:
        bx, by = max(ins[bname])
        bsegs = to_segments([p for p in d3["blocks"][bname] if p["layer"] == "----- (구조) 하부 골조"]) + np.array([bx, by, bx, by])
        con_band = sup["con"] + np.array([0, sh, 0, sh])
        dx, dy, nx, ny = find_offset(bsegs, con_band)
    G = [p for p in ml if p["layer"] == "----- (구조) Girder" and p["kind"] == "LINE" and col_of((p["x1"] + p["x2"]) / 2) == nm]
    B = [p for p in ml if p["layer"] == "----- (구조) Beam" and p["kind"] == "LINE" and col_of((p["x1"] + p["x2"]) / 2) == nm]
    off = np.array([dx, dy, dx, dy])
    gl = to_segments(G) + off; bl = to_segments(B) + off
    ref[N] = {"girder_lines": gl, "beam_lines": bl, "girder_cl": pair_centerlines(gl), "beam_cl": pair_centerlines(bl),
              "off": (dx, dy), "support": k, "shift": sh}
    print(f"도면 B{N if N else '1F'} (열 {nm}, 지지층 B{k}): 오프셋 {dx:.0f},{dy:.0f} (표 {nx},{ny})  거더선 {len(gl)}→중심선 {len(ref[N]['girder_cl'])}  보선 {len(bl)}→{len(ref[N]['beam_cl'])}")
pickle.dump(ref, open(sys.argv[3], "wb"), protocol=5)
print("saved", sys.argv[3])
