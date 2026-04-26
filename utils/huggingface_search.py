"""
huggingface_search.py
─────────────────────
HuggingFace Models + Spaces 검색

HF 공개 API (인증 불필요):
  https://huggingface.co/api/models?search=...&sort=likes&limit=N
  https://huggingface.co/api/spaces?search=...&sort=likes&limit=N
"""

from __future__ import annotations
import requests

_TIMEOUT = 10
_BASE    = "https://huggingface.co"

# pipeline_tag → 사람이 읽기 좋은 한국어 레이블
_PIPELINE_KO: dict[str, str] = {
    "text-generation":          "텍스트 생성",
    "text2text-generation":     "텍스트 변환",
    "text-to-speech":           "음성 합성 TTS",
    "automatic-speech-recognition": "음성 인식 ASR",
    "text-classification":      "텍스트 분류",
    "token-classification":     "개체명 인식",
    "question-answering":       "질의응답",
    "image-classification":     "이미지 분류",
    "object-detection":         "객체 감지",
    "image-segmentation":       "이미지 분할",
    "image-to-text":            "이미지→텍스트",
    "text-to-image":            "텍스트→이미지",
    "translation":              "번역",
    "summarization":            "요약",
    "feature-extraction":       "특징 추출 / 임베딩",
    "sentence-similarity":      "문장 유사도",
    "reinforcement-learning":   "강화학습",
    "robotics":                 "로보틱스",
    "tabular-classification":   "테이블 분류",
    "tabular-regression":       "테이블 회귀",
    "time-series-forecasting":  "시계열 예측",
    "depth-estimation":         "깊이 추정",
    "video-classification":     "비디오 분류",
    "zero-shot-classification": "Zero-shot 분류",
    "unconditional-image-generation": "이미지 생성",
    "audio-classification":     "오디오 분류",
    "voice-activity-detection": "음성 활동 감지",
}


def _get(endpoint: str, params: dict) -> list[dict]:
    try:
        r = requests.get(f"{_BASE}/api/{endpoint}", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return [{"error": str(e)}]


def _fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


# ──────────────────────────────────────────────────────────────────────────────
# Models 검색
# ──────────────────────────────────────────────────────────────────────────────
def _search_models(query: str, limit: int = 8) -> list[dict]:
    raw = _get("models", {
        "search":    query,
        "sort":      "likes",
        "direction": -1,
        "limit":     limit,
        "full":      False,
    })
    if raw and "error" in raw[0]:
        return raw

    out = []
    for m in raw:
        model_id = m.get("modelId") or m.get("id", "")
        if not model_id:
            continue

        pipeline = m.get("pipeline_tag", "")
        tags     = m.get("tags", [])
        likes    = m.get("likes", 0)
        downloads= m.get("downloads", 0)
        modified = (m.get("lastModified") or m.get("updatedAt") or "")[:10]

        # 라이브러리 태그 추출 (transformers, diffusers, peft …)
        lib_tags = [t for t in tags if t in {
            "transformers","diffusers","peft","sentence-transformers",
            "pytorch","jax","onnx","gguf","llama.cpp","stable-diffusion",
        }]

        out.append({
            "type":       "model",
            "id":         model_id,
            "url":        f"{_BASE}/{model_id}",
            "pipeline":   pipeline,
            "pipeline_ko": _PIPELINE_KO.get(pipeline, pipeline),
            "tags":       tags[:8],
            "lib_tags":   lib_tags[:3],
            "likes":      likes,
            "likes_fmt":  _fmt_count(likes),
            "downloads":  downloads,
            "downloads_fmt": _fmt_count(downloads),
            "modified":   modified,
            "summary":    m.get("description") or "",
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Spaces 검색 (웹 데모)
# ──────────────────────────────────────────────────────────────────────────────
def _search_spaces(query: str, limit: int = 5) -> list[dict]:
    raw = _get("spaces", {
        "search":    query,
        "sort":      "likes",
        "direction": -1,
        "limit":     limit,
    })
    if raw and "error" in raw[0]:
        return raw

    out = []
    for s in raw:
        space_id = s.get("id", "")
        if not space_id:
            continue

        likes    = s.get("likes", 0)
        sdk      = s.get("sdk", "")
        tags     = s.get("tags", [])
        modified = (s.get("lastModified") or s.get("updatedAt") or "")[:10]

        out.append({
            "type":       "space",
            "id":         space_id,
            "url":        f"{_BASE}/spaces/{space_id}",
            "sdk":        sdk,
            "tags":       tags[:6],
            "likes":      likes,
            "likes_fmt":  _fmt_count(likes),
            "modified":   modified,
            "summary":    s.get("cardData", {}).get("short_description", "") if isinstance(s.get("cardData"), dict) else "",
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 통합 검색 (외부에서 호출)
# ──────────────────────────────────────────────────────────────────────────────
def search_huggingface(
    query: str,
    tech_terms: list[str] | None = None,
    max_models: int = 8,
    max_spaces: int = 5,
) -> list[dict]:
    """
    Models + Spaces를 통합 검색 후 likes 기준 정렬.

    tech_terms가 있으면 기술 키워드로도 추가 검색 → 합산 후 중복 제거.
    """
    queries = [query]
    if tech_terms:
        queries += tech_terms[:2]  # 최대 2개 추가 쿼리

    models_all: list[dict] = []
    spaces_all: list[dict] = []
    seen_ids: set[str] = set()

    for q in queries:
        for item in _search_models(q, limit=max_models):
            if "error" in item:
                continue
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                models_all.append(item)

        for item in _search_spaces(q, limit=max_spaces):
            if "error" in item:
                continue
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                spaces_all.append(item)

    # likes 내림차순 정렬
    models_all.sort(key=lambda x: x["likes"], reverse=True)
    spaces_all.sort(key=lambda x: x["likes"], reverse=True)

    # Models 먼저, Spaces 뒤에
    return models_all[:max_models] + spaces_all[:max_spaces]
