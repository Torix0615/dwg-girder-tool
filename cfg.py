"""config.json 로더(기본값 병합). 각 스크립트는 `--config 경로` 또는 마지막 인자로 받는다."""
import json, os, sys

DEFAULT = {
    "층_제목_정규식": "평면도", "층_분리_간격": 10000,
    "골조_색": 2, "중심선_색": 1, "중심선_선종류_정규식": "CEN|CENTER|DASHDOT|ISO04", "중심선_레이어_정규식": "CEN|AXIS|GRID", "중심선_색_필수": False, "중심선_반복블록_제외": True, "중심선_반복블록_기준": 2, "중심선_구조만": False, "제외_레이어_정규식": "FIN|HATCH|PAT|TXT|TEXT|DIM|AREA|NOTE|SYM|DOOR|LEVEL|CONTINUOUS|FURN|BUB|조적|MASN|BRICK", "OPEN_레이어_정규식": "OPEN",
    "동_벽체_레이어": "DEF-기준층 벽체", "기둥_라벨_레이어": "CHECK-지하주차장 기둥", "동_최소면적_m2": 150, "동_선_최대길이": 12000,
    "거더_축각도_허용": 8.0, "거더_최대길이": 14000, "거더_횡오차_허용": 700, "거더_벽끝_사용": True, "거더_T접합_사용": True, "거더_최소길이": 300,
    "보_기준_거더길이": 4000, "보_베이폭_최소": 3000, "보_베이폭_2개": 8700, "보_베이폭_3개": 14000, "보_경계벽_최소두께": 250, "동구역_기둥_제외": True,
    "거더폭_X": 400, "거더폭_Y": 500, "보폭": 400, "1층바닥_생성": True, "출력_x이동": 0,
    "MGT_층고": 5000, "MGT_미세어긋남": 100, "MGT_내벽두께": 200, "MGT_외벽두께": 500, "MGT_거더춤": 700, "MGT_보춤": 600,
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
