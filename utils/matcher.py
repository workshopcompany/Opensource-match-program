import re

KEYWORD_MAP = {
    "Engineering":      ["engineering", "cfd", "simulation", "fem", "fea", "openfoam", "ansys", "matlab", "공학", "해석", "시뮬레이션", "엔지니어링"],
    "Robotics":         ["robot", "robotic", "bipedal", "quadruped", "walking", "balance", "pybullet", "mujoco", "ros", "locomotion", "로봇", "보행", "균형", "이족"],
    "AI / ML":          ["llm", "gpt", "claude", "bert", "ml", "ai", "nlp", "embedding", "transformer", "neural", "machine learning", "deep learning", "인공지능", "자동화"],
    "Manufacturing":    ["mim", "mold", "injection", "molding", "manufacturing", "powder", "shrinkage", "gate", "cooling", "사출", "성형", "금형", "제조"],
    "CFD / Simulation": ["cfd", "flow", "fluid", "openfoam", "interfoam", "simulation", "solver", "mesh", "유동", "해석", "솔버"],
    "Locomotion Control": ["bipedal", "biped", "walking", "balance", "gait", "locomotion", "이족보행", "보행", "균형"],
    "Bipedal Walking":  ["bipedal", "biped", "two-leg", "이족", "보행", "humanoid"],
    "Mold Design":      ["mold", "gate", "cooling", "injection mold", "몰드", "금형"],
    "OpenFOAM":         ["openfoam", "interfoam", "cfd", "유동"],
    "Utility":          ["dashboard", "converter", "scraper", "tool", "utility"],
    "PyBullet":         ["pybullet", "bullet", "physics sim", "물리 시뮬"],
    "ROS Integration":  ["ros", "ros2", "rosnode"],
}


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = re.split(r"[\s\-_/]+", text)
    return [t for t in tokens if len(t) > 1]


def semantic_score(app: dict, query: str) -> int:
    qt = tokenize(query)
    score = 0

    # 앱의 모든 텍스트 필드
    fields = (
        tokenize(app.get("summary", ""))
        + tokenize(app.get("name", ""))
        + tokenize(app.get("cat_major", ""))
        + tokenize(app.get("cat_mid", ""))
        + tokenize(app.get("cat_minor", ""))
        + [t.lower() for t in app.get("tags", [])]
        + app.get("kw", [])
    )

    for q in qt:
        # 직접 매칭
        for f in fields:
            if f == q:
                score += 10
            elif q in f or f in q:
                score += 5

        # 카테고리 키워드 매칭
        for cat, kws in KEYWORD_MAP.items():
            cat_tokens = tokenize(cat)
            app_cats = [
                tokenize(app.get("cat_major", "")),
                tokenize(app.get("cat_mid", "")),
                tokenize(app.get("cat_minor", "")),
            ]
            app_cat_flat = [t for group in app_cats for t in group]
            if any(kw in q or q in kw for kw in kws):
                if any(ct in app_cat_flat for ct in cat_tokens):
                    score += 15

    return min(99, score)
