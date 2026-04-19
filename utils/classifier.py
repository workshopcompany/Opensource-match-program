import os
import json
import re
import time
import urllib.request
import urllib.error

# ── Gemini 모델 우선순위 (무료 티어 소진 시 자동 폴백) ──────────────────────
GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

# API 호출 간 최소 대기 시간 (초) — 무료 티어 RPM 보호
GEMINI_CALL_DELAY = 5

# ── 키워드 기반 분류 규칙 ────────────────────────────────────────────────────
RULES = [
    {"kw": ["mim", "metal injection", "powder metallurgy", "shrinkage", "사출 성형", "분말"],
     "major": "Engineering", "mid": "Manufacturing", "minor": "MIM / Powder Metallurgy", "conf": 93},
    {"kw": ["mold", "moldiq", "gate location", "cooling channel", "injection mold", "몰드", "금형"],
     "major": "Engineering", "mid": "Manufacturing", "minor": "Mold Design", "conf": 91},
    {"kw": ["openfoam", "interfoam", "cfd", "fluid simulation", "solver", "mesh", "유동 해석"],
     "major": "Engineering", "mid": "CFD / Simulation", "minor": "OpenFOAM", "conf": 92},
    {"kw": ["fem", "fea", "finite element", "ansys", "abaqus", "유한요소"],
     "major": "Engineering", "mid": "CFD / Simulation", "minor": "FEA", "conf": 89},
    {"kw": ["thermal", "heat transfer", "temperature distribution", "열전달"],
     "major": "Engineering", "mid": "CFD / Simulation", "minor": "Thermal Analysis", "conf": 87},
    {"kw": ["shrinkage prediction", "phase diagram", "alloy", "material property", "소재"],
     "major": "Engineering", "mid": "Materials Science", "minor": "Shrinkage Prediction", "conf": 88},
    {"kw": ["bipedal", "biped", "two-leg", "이족보행", "보행 로봇", "humanoid walk"],
     "major": "Robotics", "mid": "Locomotion Control", "minor": "Bipedal Walking", "conf": 94},
    {"kw": ["quadruped", "four-leg", "gait planning", "4족"],
     "major": "Robotics", "mid": "Locomotion Control", "minor": "Quadruped Gait", "conf": 91},
    {"kw": ["balance control", "균형 제어", "stabilization", "inverted pendulum"],
     "major": "Robotics", "mid": "Locomotion Control", "minor": "Bipedal Walking", "conf": 88},
    {"kw": ["pybullet", "mujoco", "physics simulation", "robot sim"],
     "major": "Robotics", "mid": "Simulation", "minor": "PyBullet", "conf": 90},
    {"kw": ["ros", "ros2", "robotic operating system"],
     "major": "Robotics", "mid": "Simulation", "minor": "ROS Integration", "conf": 90},
    {"kw": ["slam", "lidar", "point cloud", "mapping"],
     "major": "Robotics", "mid": "Perception", "minor": "SLAM", "conf": 89},
    {"kw": ["llm", "large language model", "gpt", "gemini", "chatbot", "언어 모델"],
     "major": "AI / ML", "mid": "Automation", "minor": "LLM Wrapper", "conf": 88},
    {"kw": ["rag", "retrieval augmented", "embedding", "vector db", "semantic search"],
     "major": "AI / ML", "mid": "NLP", "minor": "RAG Pipeline", "conf": 89},
    {"kw": ["langchain", "agent", "workflow automation", "자동화 파이프라인"],
     "major": "AI / ML", "mid": "Automation", "minor": "LangChain", "conf": 87},
    {"kw": ["image segmentation", "object detection", "yolo", "vision", "이미지"],
     "major": "AI / ML", "mid": "Computer Vision", "minor": "Image Segmentation", "conf": 88},
    {"kw": ["dashboard", "visualization", "streamlit app", "데이터 시각화"],
     "major": "Utility", "mid": "Data Tools", "minor": "Dashboard", "conf": 80},
    {"kw": ["scraper", "crawler", "web scraping", "data extraction"],
     "major": "Utility", "mid": "Data Tools", "minor": "Scraper", "conf": 83},
    {"kw": ["github actions", "ci/cd", "deploy", "docker", "배포"],
     "major": "Utility", "mid": "DevOps", "minor": "GitHub Actions", "conf": 84},
]

SUMMARY_TEMPLATES = {
    "MIM / Powder Metallurgy": "금속 사출 성형(MIM) 공정을 자동화하는 무료 엔지니어링 도구입니다.",
    "Mold Design": "몰드 설계 및 최적화를 지원하는 무료 CAE 도구입니다.",
    "OpenFOAM": "OpenFOAM 기반 유동 해석을 자동화하는 무료 시뮬레이션 앱입니다.",
    "FEA": "유한요소해석(FEA) 기반 구조 해석을 수행하는 무료 도구입니다.",
    "Shrinkage Prediction": "재료 수축률을 예측하는 무료 소재 공학 계산 도구입니다.",
    "Bipedal Walking": "이족보행 로봇의 균형 제어 및 보행 패턴을 시뮬레이션하는 무료 앱입니다.",
    "Quadruped Gait": "4족 보행 로봇의 보행 계획을 구현하는 무료 로보틱스 도구입니다.",
    "PyBullet": "PyBullet 물리 엔진 기반 로봇 시뮬레이션을 제공하는 무료 앱입니다.",
    "ROS Integration": "ROS/ROS2 기반 로봇 제어를 지원하는 무료 인터페이스입니다.",
    "LLM Wrapper": "LLM API를 활용한 AI 자동화 워크플로우를 제공하는 무료 앱입니다.",
    "RAG Pipeline": "검색 증강 생성(RAG) 파이프라인을 구현하는 무료 LLM 도구입니다.",
    "Dashboard": "데이터를 시각화하고 분석하는 무료 대시보드 앱입니다.",
    "Scraper": "웹 데이터를 자동으로 수집하는 무료 스크래핑 도구입니다.",
}


def infer_category(text: str, repo_name: str = "") -> dict:
    """
    1단계: 키워드 매칭으로 빠르게 분류 (항상 실행)
    2단계: GEMINI_API_KEY가 있으면 Gemini API로 정밀 분류
           - gemini-2.0-flash 우선 시도
           - 429 (할당량 초과) 발생 시 gemini-2.0-flash-lite 자동 폴백
    """
    combined = (text + " " + repo_name).lower()

    best = None
    for rule in RULES:
        if any(kw in combined for kw in rule["kw"]):
            if best is None or rule["conf"] > best["conf"]:
                best = rule

    if best is None:
        best = {"major": "Utility", "mid": "Data Tools", "minor": "Dashboard", "conf": 50}

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key and len(text) > 50:
        result, used_model = _gemini_classify_with_fallback(text, repo_name, api_key)
        if result:
            result["_model_used"] = used_model
            return result

    summary = SUMMARY_TEMPLATES.get(
        best["minor"],
        f"{best['major']} 분야의 {best['mid']} 관련 무료 오픈소스 앱입니다."
    )
    return {
        "major": best["major"],
        "mid": best["mid"],
        "minor": best["minor"],
        "confidence": best["conf"],
        "summary": summary,
        "tags": [best["major"], best["mid"], best["minor"]],
        "_model_used": "keyword",
    }


def _gemini_classify_with_fallback(
    text: str, repo_name: str, api_key: str
) -> tuple[dict | None, str]:
    """
    GEMINI_MODELS 순서대로 시도.
    429 (할당량 초과) → 다음 모델로 폴백.
    그 외 오류 → None 반환 (키워드 결과 사용).
    호출 전 GEMINI_CALL_DELAY 초 대기 (무료 티어 RPM 보호).
    """
    prompt = _build_prompt(text, repo_name)

    for model in GEMINI_MODELS:
        # 무료 티어 Rate Limit 방지: 호출 전 5초 대기
        time.sleep(GEMINI_CALL_DELAY)

        try:
            result = _call_gemini(model, prompt, api_key)
            return result, model
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # 할당량 초과 → 다음 모델로 폴백
                continue
            # 다른 HTTP 오류는 그냥 포기
            return None, "error"
        except Exception:
            return None, "error"

    # 모든 모델 소진
    return None, "exhausted"


def _call_gemini(model: str, prompt: str, api_key: str) -> dict:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 400},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)


def _build_prompt(text: str, repo_name: str) -> str:
    return f"""GitHub 저장소를 오픈소스 앱 디렉토리용으로 분류하세요.

저장소: {repo_name}
내용:
\"\"\"
{text[:3000]}
\"\"\"

JSON만 출력 (마크다운 없이):
{{"major":"Engineering|Robotics|AI / ML|Utility|Science|Other","mid":"중분류","minor":"소분류","summary":"한 문장 한국어 요약 (이 앱은 ...을 해주는 무료 도구입니다)","confidence":0-100,"tags":["tag1","tag2","tag3"]}}"""
