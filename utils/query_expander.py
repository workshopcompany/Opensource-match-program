"""
query_expander.py
─────────────────
"내가 검색하는 방법"을 코드로 구현한 스마트 쿼리 확장기

4단계 전략:
  1. 기술 키워드 변환  — 일반어 → 논문/개발자 용어
  2. 다중 쿼리 변형   — exact / topic / alternative / awesome
  3. 연도 필터        — 최근 2년 이내 커밋 우선
  4. 품질 신호        — stars·forks·README 기준 자동 필터
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field

# ──────────────────────────────────────────────────────────────────────────────
# 1단계: 기술 키워드 사전 (일반어 → 개발자/논문 용어)
# ──────────────────────────────────────────────────────────────────────────────
_TECH_MAP: list[tuple[list[str], list[str]]] = [
    # ── 로보틱스 ──────────────────────────────────────────────────────────────
    (["이족보행", "이족 보행", "bipedal", "양발"],
     ["bipedal locomotion", "biped walking control", "humanoid balance"]),

    (["사족보행", "사족 보행", "quadruped"],
     ["quadruped gait", "quadrupedal locomotion", "legged robot control"]),

    (["균형", "밸런스", "안정화"],
     ["balance control", "stabilization", "zero moment point", "ZMP"]),

    (["로봇 시뮬레이션", "로봇 시뮬", "robot sim"],
     ["robot simulation", "physics simulation", "MuJoCo", "PyBullet", "Isaac Gym"]),

    (["로봇 제어", "모터 제어", "actuator"],
     ["robot control", "motor control", "actuator dynamics", "torque control"]),

    (["slam", "지도 작성", "위치 추정"],
     ["SLAM", "simultaneous localization mapping", "LiDAR odometry", "visual SLAM"]),

    # ── 제조 / 금속 ──────────────────────────────────────────────────────────
    (["mim", "금속분말", "분말사출", "금속 사출"],
     ["metal injection molding", "MIM", "powder metallurgy", "sintering simulation"]),

    (["수축률", "소결 수축", "shrinkage"],
     ["sintering shrinkage prediction", "MIM shrinkage", "densification model"]),

    (["몰드", "금형", "mold"],
     ["mold design", "injection mold", "tooling design", "cavity simulation"]),

    (["cnc", "가공", "절삭"],
     ["CNC machining", "toolpath generation", "G-code", "computer aided manufacturing"]),

    # ── CFD / 시뮬레이션 ──────────────────────────────────────────────────────
    (["cfd", "유동", "유체", "열해석"],
     ["computational fluid dynamics", "CFD", "OpenFOAM", "fluid simulation"]),

    (["openfoam", "오픈폼"],
     ["OpenFOAM", "finite volume method", "CFD solver", "turbulence modeling"]),

    (["fea", "구조해석", "유한요소"],
     ["finite element analysis", "FEA", "structural simulation", "stress analysis"]),

    (["열해석", "열전달", "열시뮬"],
     ["thermal analysis", "heat transfer simulation", "thermal FEA"]),

    # ── AI / ML ───────────────────────────────────────────────────────────────
    (["llm", "대형언어모델", "언어모델"],
     ["large language model", "LLM", "transformer", "foundation model"]),

    (["rag", "검색증강생성"],
     ["retrieval augmented generation", "RAG", "vector database", "semantic search"]),

    (["음성인식", "stt", "speech to text"],
     ["automatic speech recognition", "ASR", "speech-to-text", "Whisper"]),

    (["tts", "음성합성", "text to speech"],
     ["text-to-speech", "TTS", "speech synthesis", "voice cloning"]),

    (["목소리 복제", "voice clone", "음색"],
     ["voice cloning", "speaker adaptation", "tone color transfer", "zero-shot TTS"]),

    (["이미지 분할", "세그멘테이션", "segmentation"],
     ["image segmentation", "instance segmentation", "semantic segmentation", "SAM"]),

    (["객체 감지", "물체인식", "detection"],
     ["object detection", "YOLO", "real-time detection", "bounding box"]),

    (["포즈 추정", "pose estimation"],
     ["pose estimation", "human pose", "skeleton detection", "keypoint detection"]),

    (["강화학습", "rl", "reinforcement"],
     ["reinforcement learning", "RL", "policy gradient", "PPO", "SAC"]),

    (["랭체인", "langchain", "워크플로우 자동화"],
     ["LangChain", "agent workflow", "LLM orchestration", "AI automation"]),

    # ── 유틸리티 ─────────────────────────────────────────────────────────────
    (["대시보드", "시각화", "dashboard"],
     ["dashboard", "data visualization", "Grafana", "Streamlit dashboard"]),

    (["스크레이퍼", "크롤러", "scraper"],
     ["web scraper", "crawler", "data extraction", "Scrapy", "Playwright"]),

    (["파일 변환", "포맷 변환"],
     ["file converter", "format conversion", "document processing"]),

    (["모니터링", "로그", "observability"],
     ["monitoring", "observability", "logging", "Prometheus", "OpenTelemetry"]),
]


def _to_technical(query: str) -> list[str]:
    """쿼리에서 기술 키워드 목록 추출"""
    q_lower = query.lower()
    matched: list[str] = []
    for triggers, terms in _TECH_MAP:
        if any(t.lower() in q_lower for t in triggers):
            matched.extend(terms)
    return matched


# ──────────────────────────────────────────────────────────────────────────────
# 품질 기준
# ──────────────────────────────────────────────────────────────────────────────
QUALITY_PRESETS = {
    "엄격 (★1000+)":  {"min_stars": 1000, "min_forks": 50,  "months": 18},
    "권장 (★500+)":   {"min_stars": 500,  "min_forks": 20,  "months": 24},
    "넓게 (★100+)":   {"min_stars": 100,  "min_forks": 5,   "months": 36},
    "전부 보기":       {"min_stars": 0,    "min_forks": 0,   "months": 999},
}


# ──────────────────────────────────────────────────────────────────────────────
# 검색 전략 (어떤 쿼리를 생성할지)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class SearchPlan:
    """확장된 검색 플랜"""
    original: str                    # 사용자 원본 입력
    tech_terms: list[str]            # 추출된 기술 용어들
    github_queries: list[str]        # GitHub에 날릴 쿼리 목록
    reddit_queries: list[str]        # Reddit에 날릴 쿼리 목록
    awesome_topics: list[str]        # awesome-list 검색 토픽
    quality: dict                    # 품질 기준
    strategy_note: str = ""          # 사용자에게 보여줄 전략 설명


def build_plan(query: str, mode: str = "권장 (★500+)") -> SearchPlan:
    """
    4단계 검색 전략을 적용해 SearchPlan 생성

    mode: QUALITY_PRESETS 키 중 하나
    """
    quality = QUALITY_PRESETS.get(mode, QUALITY_PRESETS["권장 (★500+)"])
    tech_terms = _to_technical(query)

    # ── GitHub 쿼리 생성 ──────────────────────────────────────────────────────
    gh_queries: list[str] = []
    notes: list[str] = []

    # 원본 쿼리 (항상 포함)
    gh_queries.append(query)

    if tech_terms:
        # 기술 용어 최대 2개로 정밀 검색
        for term in tech_terms[:2]:
            if term.lower() not in query.lower():
                gh_queries.append(term)
        notes.append(f"기술 키워드 확장: {', '.join(tech_terms[:3])}")

        # 역방향 검색: 유명 서비스의 오픈소스 대안
        core = tech_terms[0].split()[0]  # 첫 번째 기술 키워드의 핵심어
        gh_queries.append(f"{core} open source alternative")
        gh_queries.append(f"self hosted {core}")
        notes.append("대안/self-hosted 역방향 검색 포함")

    # stars 필터 포함 쿼리 (고품질 우선)
    if quality["min_stars"] > 0 and tech_terms:
        primary = tech_terms[0] if tech_terms else query
        gh_queries.append(f"{primary} stars:>{quality['min_stars']}")

    # 2024~2025 연도 태깅 (최신성 강조)
    if tech_terms:
        gh_queries.append(f"{tech_terms[0]} 2024")
    notes.append("최근 2년 이내 커밋 우선 정렬")

    # ── Awesome-list 토픽 ────────────────────────────────────────────────────
    awesome_topics: list[str] = []
    for term in tech_terms[:3]:
        slug = re.sub(r"[^a-z0-9]+", "-", term.lower().split()[0]).strip("-")
        if slug:
            awesome_topics.append(f"awesome-{slug}")

    # ── Reddit 쿼리 생성 ─────────────────────────────────────────────────────
    rd_queries: list[str] = [query]
    if tech_terms:
        rd_queries.append(tech_terms[0])
        rd_queries.append(f"{tech_terms[0]} open source")
        rd_queries.append(f"best {tech_terms[0]} github")

    strategy_note = " · ".join(notes) if notes else "기본 키워드 검색"

    return SearchPlan(
        original=query,
        tech_terms=tech_terms,
        github_queries=list(dict.fromkeys(gh_queries)),   # 중복 제거
        reddit_queries=list(dict.fromkeys(rd_queries)),
        awesome_topics=awesome_topics,
        quality=quality,
        strategy_note=strategy_note,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 결과 품질 필터 & 재정렬
# ──────────────────────────────────────────────────────────────────────────────
from datetime import datetime, timezone

def _months_since_push(pushed_str: str) -> float:
    """pushed 날짜 문자열 → 경과 개월 수"""
    if not pushed_str:
        return 999
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y"):
        try:
            dt = datetime.strptime(pushed_str[:len(fmt) + 2].strip(), fmt)
            delta = datetime.utcnow() - dt
            return delta.days / 30
        except ValueError:
            continue
    return 999


def quality_filter(results: list[dict], quality: dict) -> list[dict]:
    """
    품질 기준으로 결과 필터링 + 재점수 정렬
    - min_stars, min_forks, months (최근 커밋 기준) 적용
    - is_awesome 플래그 있으면 stars 기준 완화
    """
    out = []
    for r in results:
        stars  = r.get("stars", 0) or 0
        forks  = r.get("forks", 0) or 0
        pushed = r.get("pushed", r.get("updated", ""))
        age_m  = _months_since_push(str(pushed))
        is_aw  = r.get("is_awesome", False)

        # Awesome-list 항목은 stars 기준 50% 완화
        star_thresh = quality["min_stars"] // 2 if is_aw else quality["min_stars"]

        if stars < star_thresh:
            continue
        if forks < quality["min_forks"] and not is_aw:
            continue
        if age_m > quality["months"] and not is_aw:
            continue

        # 재점수: 현재 relevance + 신선도 보너스
        freshness_bonus = max(0, 20 - int(age_m))      # 최근일수록 +20
        star_bonus      = min(20, int(stars / 500))     # 1000★ → +2, 10000★ → +20
        r = dict(r)  # 원본 수정 방지
        r["relevance"] = min(100, (r.get("relevance") or 0) + freshness_bonus + star_bonus)
        out.append(r)

    # relevance 내림차순 정렬
    return sorted(out, key=lambda x: x.get("relevance", 0), reverse=True)


def deduplicate(results: list[dict]) -> list[dict]:
    """repo 기준 중복 제거 (relevance 높은 것 유지)"""
    seen: dict[str, dict] = {}
    for r in results:
        repo = r.get("repo", "")
        if repo not in seen or r.get("relevance", 0) > seen[repo].get("relevance", 0):
            seen[repo] = r
    return list(seen.values())
