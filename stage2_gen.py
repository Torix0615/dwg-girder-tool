"""2단계 생성(비교 없음): 모델(s2_model.pkl)에서 층별 거더·보를 만들어 s2_result.pkl 로 저장.
python stage2_gen.py out/s2_model.pkl out/s2_result.pkl [--config config.json] [--report f]
도면 N 의 지지층 = N+1 (최하층은 거더 없음), 1F(=0) 는 B1 기둥 기준(설정 1층바닥_생성).
"""
import sys, pickle, time
import numpy as np
from cfg import pop_config_arg
import stage2_engine as E

CFG, argv = pop_config_arg(sys.argv[1:])
model_p, out_p = argv[0], argv[1]
report = argv[argv.index("--report") + 1] if "--report" in argv else None
M = pickle.load(open(model_p, "rb")); FY, H, model = M["FY"], M["H"], M["model"]

P = E.Params()
P.ANG = float(CFG["거더_축각도_허용"]); P.LMAX = float(CFG["거더_최대길이"]); P.PERP_MIN = float(CFG["거더_횡오차_허용"])
P.WALL_GIRDER = bool(CFG["거더_벽끝_사용"]); P.T_JUNCTION = bool(CFG["거더_T접합_사용"]); P.MIN_GIRDER = float(CFG["거더_최소길이"])
P.SPLIT = float(CFG["보_기준_거더길이"]); P.D_MIN = float(CFG["보_베이폭_최소"]); P.D_TWO = float(CFG["보_베이폭_2개"]); P.D_THREE = float(CFG["보_베이폭_3개"])
P.BEAM_WALL_TH = float(CFG["보_경계벽_최소두께"]); P.EXCLUDE_DONG = bool(CFG["동구역_기둥_제외"])
P.BEAM_LMAX = P.LMAX

lines = []
def out(s):
    print(s, flush=True); lines.append(s)

result = {}
floors = sorted(model)
targets = [N for N in floors if (N + 1) in model]
if CFG.get("1층바닥_생성", True) and 1 in model:
    targets = [0] + targets
for N in targets:
    k = N + 1 if N >= 1 else 1
    sh = (FY[N] - FY[k]) if N >= 1 else 0.0
    t0 = time.time()
    girders, beams = E.generate(model[k]["cols"], model[k]["con"], P, dong=model[k].get("dong"), con_th=model[k].get("con_th"))
    G = E.to_segs(girders) + np.array([0, sh, 0, sh]); B = E.to_segs(beams) + np.array([0, sh, 0, sh])
    kinds = {}
    for g in girders:
        kinds[g["kb"]] = kinds.get(g["kb"], 0) + 1
    result[N] = {"girders": girders, "beams": beams, "shift": sh, "support": k, "G": G, "B": B}
    out(f"도면 {'B'+str(N) if N else '1F'} (지지층 B{k}, 기둥 {len(model[k]['cols'])}개): 거더 {len(girders)}개 {kinds}, 보 {len(beams)}개  {time.time()-t0:.1f}s")
out(f"최하층 B{max(floors)} 은 거더 없음(아래층 없음)")
pickle.dump({"result": result, "P": {kk: getattr(P, kk) for kk in dir(P) if kk.isupper()}}, open(out_p, "wb"), protocol=5)
if report:
    open(report, "w", encoding="utf-8").write("\n".join(lines))
print("saved", out_p)
