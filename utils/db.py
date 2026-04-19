import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "apps.json"

SEED_DATA = [
    {
        "id": 1, "name": "MIM-Ops Pro", "repo": "Saferworld0/mim-ops-pro",
        "owner": "Saferworld0",
        "summary": "금속 사출 성형(MIM) 공정 전체를 자동화하는 파이프라인. DFM 분석, CFD 유동 해석, 수축률 예측, 몰드 보상까지 엔드투엔드 처리.",
        "cat_major": "Engineering", "cat_mid": "Manufacturing", "cat_minor": "MIM / Powder Metallurgy",
        "lang": "Python", "stars": 12, "has_readme": True,
        "tags": ["MIM", "DFM", "CFD", "Streamlit", "shrinkage"],
    },
    {
        "id": 2, "name": "MOLDIQ", "repo": "Saferworld0/moldiq",
        "owner": "Saferworld0",
        "summary": "몰드 설계 인텔리전스 플랫폼. 수지 유동 시뮬레이션 결과를 기반으로 게이트 위치 및 냉각 채널 최적화를 자동 추천.",
        "cat_major": "Engineering", "cat_mid": "Manufacturing", "cat_minor": "Mold Design",
        "lang": "Python", "stars": 8, "has_readme": False,
        "tags": ["mold", "gate", "cooling", "optimization"],
    },
    {
        "id": 3, "name": "OpenFOAM interFoam Automator", "repo": "Saferworld0/openfoam-interfacial",
        "owner": "Saferworld0",
        "summary": "OpenFOAM interFoam 솔버를 Streamlit UI로 감싸 비전문가도 2상 유동 해석을 실행할 수 있게 만든 자동화 앱.",
        "cat_major": "Engineering", "cat_mid": "CFD / Simulation", "cat_minor": "OpenFOAM",
        "lang": "Python", "stars": 21, "has_readme": True,
        "tags": ["OpenFOAM", "interFoam", "CFD", "simulation"],
    },
    {
        "id": 4, "name": "Bipedal Balance Controller", "repo": "example/bipedal-balance",
        "owner": "example",
        "summary": "PyBullet 기반 이족보행 로봇의 실시간 균형 제어 시뮬레이터. PID 및 LQR 컨트롤러를 Streamlit으로 시각화.",
        "cat_major": "Robotics", "cat_mid": "Locomotion Control", "cat_minor": "Bipedal Walking",
        "lang": "Python", "stars": 34, "has_readme": True,
        "tags": ["PyBullet", "bipedal", "balance", "PID", "LQR"],
    },
]


def load_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        save_db(SEED_DATA)
        return SEED_DATA
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
