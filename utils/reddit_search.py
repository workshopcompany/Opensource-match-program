"""
Reddit 검색 — 공식 JSON API (인증 불필요, 무료)

개선 사항:
  1) 한국어 쿼리 → 영어 번역 후 검색 (Gemini 있을 때)
  2) 서브레딧 확장: 도메인별 전문 서브레딧으로 동적 선택
  3) 전체 Reddit 검색(restrict_sr=false) + 서브레딧 타겟 검색 병행
  4) 결과 relevance 점수 부여 (제목 키워드 매칭 기반)
  5) 오래된 포스트 필터링 (2년 이내)
"""
import json
import time
import re
import os
import urllib.request
import urllib.parse
import urllib.error

REDDIT_DELAY = 2.0  # Reddit 공개 API 2초 간격
_last_call: float = 0.0

# ── 도메인별 서브레딧 맵 ──────────────────────────────────────────────────────
DOMAIN_SUBREDDITS: dict[str, list[str]] = {
    "robotics": [
        "robotics", "ROS", "PyBullet", "reinforcementlearning",
        "MachineLearning", "learnmachinelearning", "engineering",
    ],
    "ml_ai": [
        "MachineLearning", "learnmachinelearning", "artificial",
        "ArtificialIntelligence", "deeplearning", "LanguageModels",
        "LocalLLaMA", "Python",
    ],
    "engineering": [
        "engineering", "MechanicalEngineering", "CFD",
        "FEA", "Python", "SciPy",
    ],
    "data_tools": [
        "Python", "datascience", "dataengineering",
        "learnpython", "opensource", "programming",
    ],
    "devops": [
        "devops", "sysadmin", "selfhosted",
        "homelab", "github", "opensource",
    ],
    "other": [
        "opensource", "Python", "programming",
        "learnprogramming", "software", "SideProject",
    ],
}

# 항상 포함할 기본 서브레딧
BASE_SUBREDDITS = ["opensource", "Python", "programming"]

GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]
GEMINI_DELAY  = 5
_last_gemini_call: float = 0.0


# ── Gemini: 쿼리 번역 + 도메인 감지 ─────────────────────────────────────────
def _call_gemini(prompt: str, api_key: str, max_tokens: int = 300) -> str | None:
    global _last_gemini_call
    elapsed = time.time() - _last_gemini_call
    if elapsed < GEMINI_DELAY:
        time.sleep(GEMINI_DELAY - elapsed)

    for model in GEMINI_MODELS:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens},
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            _last_gemini_call = time.time()
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                continue
            return None
        except Exception:
            return None
    return None


def _translate_and_detect(user_query: str, api_key: str) -> dict:
    """
    한국어 포함 쿼리를 영어로 번역하고 도메인을 감지합니다.
    반환: {"en_query": str, "domain": str, "keywords": [str]}
    """
    prompt = f"""Translate and analyze this search query for Reddit search.

Query: "{user_query}"

Output ONLY valid JSON (no markdown):
{{
  "en_query": "English translation/version of the query (2-6 words, optimized for Reddit search)",
  "domain": "one of: robotics, ml_ai, engineering, data_tools, devops, other",
  "keywords": ["2-4 key English terms extracted from the query for relevance scoring"]
}}

Examples:
- "이족보행 로봇 시뮬레이션" → {{"en_query": "bipedal robot simulation", "domain": "robotics", "keywords": ["bipedal", "robot", "simulation", "locomotion"]}}
- "RAG pipeline python 무료" → {{"en_query": "RAG pipeline python open source", "domain": "ml_ai", "keywords": ["RAG", "pipeline", "retrieval", "langchain"]}}
- "OpenFOAM 유동 해석" → {{"en_query": "OpenFOAM CFD simulation", "domain": "engineering", "keywords": ["OpenFOAM", "CFD", "fluid", "simulation"]}}

Output:"""

    raw = _call_gemini(prompt, api_key, max_tokens=200)
    if not raw:
        return {"en_query": user_query, "domain": "other", "keywords": [user_query]}
    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        if "en_query" not in result:
            return {"en_query": user_query, "domain": "other", "keywords": [user_query]}
        return result
    except Exception:
        return {"en_query": user_query, "domain": "other", "keywords": [user_query]}


# ── Reddit API 요청 ───────────────────────────────────────────────────────────
def _reddit_request(url: str) -> dict | None:
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < REDDIT_DELAY:
        time.sleep(REDDIT_DELAY - elapsed)

    headers = {
        "User-Agent": "OpenSourceMatchmaker/2.0 (research tool)",
        "Accept": "application/json",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        _last_call = time.time()
        return data
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return {"_error": "rate_limit"}
        if e.code == 403:
            return {"_error": "forbidden"}
        return {"_error": str(e.code)}
    except Exception as e:
        return {"_error": str(e)}


def _parse_posts(data: dict | None, keywords: list[str]) -> list[dict]:
    """Reddit API 응답을 파싱하고 기본 relevance 점수를 계산합니다."""
    if not data or "_error" in data:
        return []

    results = []
    kw_lower = [k.lower() for k in keywords]
    cutoff_ts = time.time() - 2 * 365 * 24 * 3600  # 2년 이내

    posts = data.get("data", {}).get("children", [])
    for post in posts:
        p = post.get("data", {})

        # 오래된 포스트 필터링
        created = p.get("created_utc", 0)
        if created < cutoff_ts:
            continue

        title    = p.get("title", "")
        selftext = p.get("selftext", "")
        snippet  = selftext[:200].replace("\n", " ").strip() if selftext else ""

        # 키워드 매칭 기반 relevance 점수
        title_lower = title.lower()
        text_lower  = (selftext + " " + " ".join(p.get("url", "").split())).lower()
        hits = sum(1 for kw in kw_lower if kw in title_lower) * 20
        hits += sum(1 for kw in kw_lower if kw in text_lower) * 5
        relevance = min(95, hits)

        # 점수 없어도 upvote/comments 높으면 포함
        score = p.get("score", 0)

        results.append({
            "title":     title,
            "url":       f"https://www.reddit.com{p.get('permalink', '')}",
            "subreddit": p.get("subreddit_name_prefixed", ""),
            "score":     score,
            "summary":   snippet if snippet else "본문 없음",
            "comments":  p.get("num_comments", 0),
            "created":   int(created),
            "relevance": relevance,
            "source":    "reddit",
        })
    return results


# ── 메인 함수 ─────────────────────────────────────────────────────────────────
def search_reddit(query: str, max_results: int = 8) -> list[dict]:
    """
    개선된 Reddit 검색:
    1) Gemini로 쿼리 번역 + 도메인 감지
    2) 도메인별 전문 서브레딧 선택
    3) 전체 Reddit 검색 + 서브레딧 타겟 검색 병행
    4) 중복 제거 후 relevance + score 기준 정렬
    """
    api_key = os.environ.get("GEMINI_API_KEY")

    # ── 쿼리 번역 + 도메인 감지 ──────────────────────────────────────────────
    if api_key:
        parsed   = _translate_and_detect(query, api_key)
        en_query = parsed.get("en_query", query)
        domain   = parsed.get("domain", "other")
        keywords = parsed.get("keywords", [query])
    else:
        en_query = query
        domain   = "other"
        keywords = query.split()[:4]

    # ── 서브레딧 선택 ────────────────────────────────────────────────────────
    domain_subs = DOMAIN_SUBREDDITS.get(domain, DOMAIN_SUBREDDITS["other"])
    # 도메인 서브레딧 + 기본 서브레딧 합치되 중복 제거
    all_subs = list(dict.fromkeys(domain_subs + BASE_SUBREDDITS))

    # ── 검색 1: 전체 Reddit (restrict_sr=false) ───────────────────────────────
    params_global = urllib.parse.urlencode({
        "q":           en_query,
        "sort":        "relevance",
        "limit":       max_results,
        "t":           "year",
        "restrict_sr": "false",
    })
    url_global = f"https://www.reddit.com/search.json?{params_global}"
    global_data = _reddit_request(url_global)
    global_posts = _parse_posts(global_data, keywords)

    # ── 검색 2: 도메인 서브레딧 타겟 검색 ────────────────────────────────────
    subreddit_str = "+".join(all_subs[:6])
    params_sub = urllib.parse.urlencode({
        "q":           en_query,
        "sort":        "relevance",
        "limit":       max_results,
        "t":           "year",
        "restrict_sr": "true",
    })
    url_sub = f"https://www.reddit.com/r/{subreddit_str}/search.json?{params_sub}"
    sub_data = _reddit_request(url_sub)
    sub_posts = _parse_posts(sub_data, keywords)

    # ── 중복 제거 + 병합 ─────────────────────────────────────────────────────
    seen_urls: set[str] = set()
    all_posts: list[dict] = []
    for post in global_posts + sub_posts:
        if post["url"] not in seen_urls:
            seen_urls.add(post["url"])
            all_posts.append(post)

    if not all_posts:
        err = ""
        if global_data and "_error" in global_data:
            err = global_data["_error"]
        if err == "rate_limit":
            return [{"error": "Reddit rate limit 초과. 잠시 후 다시 시도하세요."}]
        return [{"error": "Reddit 검색 결과가 없습니다."}]

    # ── 정렬: relevance 우선, 동점이면 upvote 순 ─────────────────────────────
    all_posts.sort(key=lambda p: (p["relevance"], p["score"]), reverse=True)

    # ── 번역 정보 메타데이터 추가 (UI 표시용) ────────────────────────────────
    for p in all_posts:
        p["searched_as"] = en_query  # UI에서 "'{en_query}'로 검색됨" 표시 가능

    return all_posts[:max_results]
