"""config.json 로더(기본값 병합). 각 스크립트는 `--config 경로` 또는 마지막 인자로 받는다."""
import json, os, sys

DEFAULT = {
    "층_블록_정규식": r"지하(\d)층 주차장 평면도$", "층_간격": 0,
    "골조_레이어": ["CON", "COL"], "골조_색": 2, "기둥_레이어": "COL",
    "중심선_레이어": ["CEN", "CEN-1", "CEN-PARK"], "OPEN_레이어": "OPEN",
    "동_벽체_레이어": "DEF-기준층 벽체", "동_최소면적_m2": 150, "동_선_최대길이": 12000,
    "거더_축각도_허용": 8.0, "거더_최대길이": 14000, "거더_횡오차_허용": 700, "거더_벽끝_사용": True, "거더_T접합_사용": True, "거더_최소길이": 300,
    "보_기준_거더길이": 4000, "보_베이폭_최소": 3000, "보_베이폭_2개": 8700, "보_베이폭_3개": 14000, "보_경계벽_최소두께": 250, "동구역_기둥_제외": True,
    "거더폭_X": 400, "거더폭_Y": 500, "보폭": 400, "1층바닥_생성": True, "출력_x이동": 0,
    "출력_레이어": {"골조": "----- (구조) 골조", "중심선": "----- (구조) 중심선", "OPEN": "----- (구조) OPEN",
                "하부골조": "----- (구조) 하부 골조", "동구역": "----- (구조) 동 구역", "거더": "GIRDER", "보": "BEAM"},
}


def load_cfg(path=None):
    cfg = json.loads(json.dumps(DEFAULT, ensure_ascii=False))
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(path):
        user = json.load(open(path, encoding="utf-8"))
        for k, v in user.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def pop_config_arg(argv):
    """argv 에서 --config X 를 떼어내고 (cfg, 나머지 argv) 반환"""
    path = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--config" and i + 1 < len(argv):
            path = argv[i + 1]; i += 2; continue
        rest.append(argv[i]); i += 1
    return load_cfg(path), rest
