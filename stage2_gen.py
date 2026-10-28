"""2단계 생성: 모델(s2_model.pkl)에서 층별 거더·보를 만들어 s2_result.pkl 로 저장.
python stage2_gen.py out/s2_model.pkl out/s2_result.pkl [--config config.json] [--report f]
규칙: 도면 N 층의 거더·보는 바로 아래층(지지층)의 기둥·벽 위에 그린다. 최하층은 아래층이 없어 거더 없음.
      1층 도면이 없고 지하층만 있으면(설정 1층바닥_생성) 1층 바닥을 최상 지하층 기둥으로 만들어 그 위 띠에 둔다.
결과[N] = {girders, beams(지지층 좌표), shift(dx,dy: 지지층→N층 위치), support, G, B(이동 적용 선분)}
"""
import sys, pickle, time
import numpy as np
from cfg import pop_config_arg
import stage2_engine as E

CFG, argv = pop_config_arg(sys.argv[1:])
model_p, out_p = argv[0], argv[1]
report = argv[argv.index("--report") + 1] if "--report" in argv else None
M = pickle.load(open(model_p, "rb")); floors, model = M["floors"], M["model"]

P = E.Params()
P.ANG = float(CFG["거더_축각도_허용"]); P.LMAX = float(CFG["거더_최대길이"]); P.PERP_MIN = float(CFG["거더_횡오차_허용"])
P.WALL_GIRDER = bool(CFG["거더_벽끝_사용"]); P.T_JUNCTION = bool(CFG["거더_T접합_사용"]); P.MIN_GIRDER = float(CFG["거더_최소길이"])
P.SPLIT = float(CFG["보_기준_거더길이"]); P.D_MIN = float(CFG["보_베이폭_최소"]); P.D_TWO = float(CFG["보_베이폭_2개"]); P.D_THREE = float(CFG["보_베이폭_3개"])
P.BEAM_WALL_TH = float(CFG["보_경계벽_최소두께"]); P.EXCLUDE_DONG = bool(CFG["동구역_기둥_제외"])
P.BEAM_LMAX = P.LMAX

lines = []
def out(s):
    print(s, flush=True); lines.append(s)

order = [f["id"] for f in floors]
anchor = {f["id"]: np.array(f["anchor"], dtype=float) for f in floors}
short = {f["id"]: f["short"] for f in floors}
pairs = [(order[i], order[i - 1]) for i in range(1, len(order))]  # (도면 층, 지지층=바로 아래층)
synth = None
if CFG.get("1층바닥_생성", True) and not any(1 <= k < 1000 for k in order) and -1 in order:
    # 1층 도면이 없는 지하주차장 도면: 1층 바닥을 B1 기둥으로 생성, 위치는 층 간격만큼 위로 외삽
    step = anchor[-1] - anchor[-2] if -2 in anchor else np.array([0.0, 0.0])
    anchor[1] = anchor[-1] + step; short[1] = "1F"; synth = 1
    pairs.append((1, -1))
    floors = floors + [{"id": 1, "label": "1층 바닥(생성)", "short": "1F", "anchor": tuple(anchor[1].tolist()), "bbox": None, "n": 0, "synth": True}]

result = {}
for N, k in pairs:
    sh = anchor[N] - anchor[k]
    t0 = time.time()
    m = model[k]
    if not m["cols"]:
        out(f"도면 {short[N]} (지지층 {short[k]}): 기둥 없음 → 거더 생략"); continue
    girders, beams = E.generate(m["cols"], m["con"], P, dong=m.get("dong"), con_th=m.get("con_th"))
    off = np.array([sh[0], sh[1], sh[0], sh[1]])
    G = E.to_segs(girders) + off if girders else np.zeros((0, 4)); B = E.to_segs(beams) + off if beams else np.zeros((0, 4))
    kinds = {}
    for g in girders:
        kinds[g["kb"]] = kinds.get(g["kb"], 0) + 1
    result[N] = {"girders": girders, "beams": beams, "shift": (float(sh[0]), float(sh[1])), "support": k, "G": G, "B": B}
    out(f"도면 {short[N]} (지지층 {short[k]}, 기둥 {len(m['cols'])}개): 거더 {len(girders)}개 {kinds}, 보 {len(beams)}개  {time.time()-t0:.1f}s")
out(f"최하층 {short[order[0]]} 은 거더 없음(아래층 없음)")
pickle.dump({"result": result, "floors": floors, "P": {kk: getattr(P, kk) for kk in dir(P) if kk.isupper()}}, open(out_p, "wb"), protocol=5)
if report:
    open(report, "w", encoding="utf-8").write("\n".join(lines))
print("saved", out_p)
