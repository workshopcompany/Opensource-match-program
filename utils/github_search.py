"""
GitHub Search API — 무료, 인증 없이 10 req/min
GITHUB_TOKEN 환경변수 설정 시 30 req/min으로 상향

개선된 Gemini 연동:
  1) 쿼리 의도(intent) 분석 → 검색 타입 결정 (라이브러리/GUI앱/시뮬레이션/교육예제 등)
  2) 한국어 포함 자연어 → 영어 GitHub 키워드 + topic 태그 + awesome 키워드로 확장
  3) 일반 검색 + GitHub Topics 검색 + Awesome-list 검색 병렬 수행
  4) 상위 후보 전체를 한 번의 Gemini 호출로 배치 재순위(batch re-ranking)
"""
import os
import json
import time
import re
import urllib.request
import urllib.parse
import urllib.error

GITHUB_API    = "https://api.github.com"
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]
GEMINI_DELAY  = 5   # 무료 티어 Rate Limit 보호
GH_DELAY      = 6   # GitHub 비인증 10 req/min → 6초 간격

_last_gh_call:     float = 0.0
_last_gemini_call: float = 0.0


# ── Gemini 호출 공통 ──────────────────────────────────────────────────────────
def _call_gemini(prompt: str, api_key: str, max_tokens: int = 800) -> str | None:
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
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_tokens,
                "response_mime_type": "application/json",
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
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


# ── STEP 1-A: 쿼리 의도(intent) 분석 ────────────────────────────────────────
def analyze_intent(user_query: str, api_key: str) -> dict:
    """
    Gemini가 사용자 쿼리를 분석해 검색 전략을 결정합니다.
    반환: {
        "type": "simulation|library|gui_app|cli_tool|tutorial|dataset|other",
        "domain": "robotics|ML|engineering|data|devops|other",
        "keywords": [...],       # 일반 GitHub 키워드 3~5개
        "topics": [...],         # GitHub topic 태그 2~4개
        "awesome_keywords": [...] # awesome-list 검색용 1~2개
    }
    """
    prompt = f"""You are a GitHub search strategy expert.

Analyze the user's query and return a JSON search plan.

User query: "{user_query}"

Rules:
- Output ONLY valid JSON, no explanation, no markdown fences
- "type": one of [simulation, library, gui_app, cli_tool, tutorial, dataset, framework, other]
- "domain": one of [robotics, ml_ai, engineering, data_tools, devops, other]
- "keywords": 3-5 English GitHub search phrases (2-4 words each), optimized for repo names/descriptions
- "topics": 2-4 GitHub topic tag strings (lowercase-hyphenated, e.g. "bipedal-robot"), used in topic: searches
- "awesome_keywords": 1-2 terms for searching awesome-lists (e.g. "robotics", "bipedal")
- If Korean input, translate and expand appropriately

Example for "이족보행 로봇 PID 제어 시뮬레이션":
{{
  "type": "simulation",
  "domain": "robotics",
  "keywords": ["bipedal walking simulation", "biped PID control", "humanoid locomotion PyBullet", "bipedal balance robot"],
  "topics": ["bipedal-robot", "locomotion", "pid-control", "robotics-simulation"],
  "awesome_keywords": ["robotics", "bipedal"]
}}

Output JSON:"""

    raw = _call_gemini(prompt, api_key, max_tokens=400)
    if not raw:
        return _fallback_intent(user_query)
    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        # 필수 키 검증
        for k in ("keywords", "topics", "awesome_keywords"):
            if k not in result or not isinstance(result[k], list):
                return _fallback_intent(user_query)
        return result
    except Exception:
        return _fallback_intent(user_query)


def _fallback_intent(user_query: str) -> dict:
    """
    Gemini 없을 때 기본 fallback.
    한국어가 포함된 경우 영어 단어만 추출하고,
    한국어 전용 쿼리는 도메인 키워드 사전으로 보완합니다.
    """
    import unicodedata

    # 한글 포함 여부 판단
    has_korean = any(unicodedata.category(c) == "Lo" and "\uAC00" <= c <= "\uD7A3" for c in user_query)

    if not has_korean:
        # 영어 쿼리: 그대로 사용
        return {
            "type": "other", "domain": "other",
            "keywords": [user_query],
            "topics": [], "awesome_keywords": [],
        }

    # 한국어 쿼리: 도메인 키워드 매핑으로 영어 변환 시도
    KO_MAP = {
        # 로보틱스
        "이족보행": ["bipedal walking", "biped robot"],
        "보행":     ["locomotion", "walking robot"],
        "균형":     ["balance control", "stabilization"],
        "제어":     ["control", "controller"],
        "시뮬레이션": ["simulation", "simulator"],
        "로봇":     ["robot", "robotics"],
        "강화학습": ["reinforcement learning", "RL"],
        # 공학
        "유동":     ["fluid dynamics", "CFD"],
        "해석":     ["analysis", "simulation"],
        "열":       ["thermal", "heat transfer"],
        "몰드":     ["mold design", "injection mold"],
        "설계":     ["design optimization"],
        "수축률":   ["shrinkage prediction"],
        "분말":     ["powder metallurgy"],
        # AI/ML
        "파이프라인": ["pipeline"],
        "분류":     ["classification"],
        "탐지":     ["detection"],
        "생성":     ["generation", "generative"],
        # 일반
        "파이썬":   ["python"],
        "무료":     ["open source", "free"],
        "자동":     ["automation", "automatic"],
        "최적화":   ["optimization"],
        "예측":     ["prediction"],
        "학습":     ["training", "learning"],
    }

    matched_en: list[str] = []
    for ko, en_list in KO_MAP.items():
        if ko in user_query:
            matched_en.extend(en_list)

    # 영어 단어가 쿼리에 섞여 있으면 그것도 포함
    en_words = [w for w in user_query.split() if all(ord(c) < 128 for c in w) and len(w) > 1]
    matched_en.extend(en_words)

    if not matched_en:
        # 매핑 실패 시 원문 그대로 (최후 수단)
        matched_en = [user_query]

    # 조합해서 2~3개 키워드 문구 생성
    keywords = []
    if len(matched_en) >= 2:
        keywords.append(" ".join(matched_en[:2]))
        keywords.append(" ".join(matched_en[:3]) if len(matched_en) >= 3 else matched_en[0])
    keywords.append(" ".join(matched_en))
    keywords = list(dict.fromkeys(keywords))[:4]  # 중복 제거, 최대 4개

    return {
        "type": "other", "domain": "other",
        "keywords": keywords,
        "topics": [],
        "awesome_keywords": matched_en[:1],
    }


# ── GitHub API 공통 요청 ──────────────────────────────────────────────────────
def _gh_request(url: str, delay: float = GH_DELAY) -> dict | None:
    global _last_gh_call
    elapsed = time.time() - _last_gh_call
    if elapsed < delay:
        time.sleep(delay - elapsed)

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpenSourceMatchmaker/2.0",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            _last_gh_call = time.time()
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return {"_error": "rate_limit"}
        return {"_error": str(e.code)}
    except Exception as e:
        return {"_error": str(e)}


# ── STEP 2-A: 일반 키워드 검색 ───────────────────────────────────────────────
def _search_by_keyword(keyword: str, per_page: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": keyword,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    })
    data = _gh_request(f"{GITHUB_API}/search/repositories?{params}")
    return _parse_repos(data, "keyword")


# ── STEP 2-B: GitHub Topics 검색 ─────────────────────────────────────────────
def _search_by_topic(topic: str, per_page: int = 5) -> list[dict]:
    """
    GitHub topic 태그로 검색 — keyword 검색보다 분류가 정확함
    예: topic:bipedal-robot
    """
    params = urllib.parse.urlencode({
        "q": f"topic:{topic}",
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    })
    data = _gh_request(f"{GITHUB_API}/search/repositories?{params}")
    return _parse_repos(data, "topic")


# ── STEP 2-C: Awesome-list 검색 ──────────────────────────────────────────────
def _search_awesome_lists(keyword: str, per_page: int = 3) -> list[dict]:
    """
    'awesome + {keyword}' 큐레이션 목록 저장소 검색.
    awesome-list는 사람이 직접 검증한 고품질 링크 모음이라 신뢰도가 높음.
    awesome-list 자체는 별도 카드로 표시.
    """
    params = urllib.parse.urlencode({
        "q": f"awesome {keyword} in:name,description",
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    })
    data = _gh_request(f"{GITHUB_API}/search/repositories?{params}")
    repos = _parse_repos(data, "awesome")
    # is_awesome 플래그 추가
    for r in repos:
        r["is_awesome"] = True
    return repos


def _parse_repos(data: dict | None, source_tag: str) -> list[dict]:
    if not data or "_error" in data:
        # 💡 추가된 디버깅 코드: 에러가 나면 터미널(콘솔)에 빨간 글씨로 이유를 출력합니다.
        if data and "_error" in data:
            print(f"🚨 [GitHub API 에러 - {source_tag}] 원인: {data['_error']}")
        return []
    results = []
    for item in data.get("items", []):
        results.append({
            "name":    item.get("name", ""),
            "repo":    item.get("full_name", ""),
            "owner":   item.get("owner", {}).get("login", ""),
            "summary": item.get("description") or "",
            "stars":   item.get("stargazers_count", 0),
            "lang":    item.get("language") or "Unknown",
            "url":     item.get("html_url", ""),
            "topics":  item.get("topics", []),
            "updated": item.get("updated_at", "")[:10],
            "pushed":  item.get("pushed_at", "")[:10],   # 최근 커밋 기준 활성도
            "forks":   item.get("forks_count", 0),
            "open_issues": item.get("open_issues_count", 0),
            "source":  "github",
            "search_source": source_tag,  # keyword / topic / awesome
            "readme":  "",
            "gemini_summary": "",
            "relevance": 0,
            "is_awesome": False,
        })
    return results


# ── STEP 3: README 가져오기 ───────────────────────────────────────────────────
def _fetch_readme(repo_full_name: str) -> str:
    data = _gh_request(f"{GITHUB_API}/repos/{repo_full_name}/readme")
    if not data or "_error" in data:
        return ""
    import base64
    content  = data.get("content", "")
    encoding = data.get("encoding", "")
    if encoding == "base64":
        try:
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
            return decoded[:3000]
        except Exception:
            return ""
    return content[:3000]
# 2. 메인 검색 로직 내의 STEP 3 (이 부분을 바꾸시는 겁니다)
# ── STEP 3: README 순차 수집 ──
pre_sorted = sorted(candidates, key=lambda r: r["stars"], reverse=True)
readme_count = min(3, len(pre_sorted)) if api_key else 0
top_for_readme = pre_sorted[:readme_count]

# ThreadPoolExecutor 부분을 삭제하고 이 for문으로 교체
for c in top_for_readme:
    # _fetch_readme 내부의 _gh_request가 6초 대기를 수행함
    c["readme"] = _fetch_readme(c["repo"])

# ── STEP 4: 배치 재순위 (핵심 개선) ──────────────────────────────────────────
def _batch_rerank(candidates: list[dict], user_query: str, api_key: str) -> list[dict]:
    """
    상위 후보 전체를 한 번의 Gemini 호출로 재순위.
    기존: 후보마다 Gemini 1회 호출 → N회 호출, 느리고 API 낭비.
    개선: 모든 후보를 하나의 프롬프트에 담아 ranked list 반환 → 1회 호출.
    """
    if not candidates:
        return candidates

    # 후보 목록을 간결하게 정리 (토큰 절약)
    repo_list = []
    for i, r in enumerate(candidates):
        readme_snip = r.get("readme", "")[:500]
        repo_list.append(
            f'[{i}] {r["repo"]} | ★{r["stars"]} | {r.get("lang","")} | '
            f'topics: {",".join(r.get("topics",[])[:4])} | '
            f'desc: {r.get("summary","")[:100]} | '
            f'readme: {readme_snip[:200]}'
        )

    prompt = f"""You are evaluating GitHub repositories for a user's need.

User's need (may be in Korean): "{user_query}"

Below are {len(repo_list)} candidate repositories:

{chr(10).join(repo_list)}

Task:
1. Score each repository 0-100 for relevance to the user's need
2. Write a Korean one-line summary (50자 이내) per repo
3. Write a Korean reason (30자 이내) per repo

Output ONLY a JSON array in this exact format (no markdown, no explanation):
[
  {{"idx": 0, "relevance": 85, "summary_ko": "...", "reason": "..."}},
  {{"idx": 1, "relevance": 40, "summary_ko": "...", "reason": "..."}},
  ...
]

Include ALL {len(repo_list)} items. Output:"""

    raw = _call_gemini(prompt, api_key, max_tokens=1200)
    if not raw:
        return _star_fallback(candidates)

    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        scores = json.loads(raw)
        score_map = {item["idx"]: item for item in scores if isinstance(item, dict)}
        for i, repo in enumerate(candidates):
            s = score_map.get(i, {})
            candidates[i]["relevance"]      = s.get("relevance", 0)
            candidates[i]["gemini_summary"] = s.get("summary_ko", repo["summary"])
            candidates[i]["reason"]         = s.get("reason", "")
        return candidates
    except Exception:
        return _star_fallback(candidates)


def _star_fallback(candidates: list[dict]) -> list[dict]:
    """Gemini 없을 때 stars 기반 점수"""
    for r in candidates:
        r["relevance"]      = min(50, r["stars"] // 20)
        r["gemini_summary"] = r["summary"]
        r["reason"]         = "별점 기준"
    return candidates


# ── 메인 함수 ─────────────────────────────────────────────────────────────────
def search_github(
    user_query: str,
    max_results: int = 10,
    use_gemini: bool = True,
) -> list[dict]:
    """
    개선된 3단계 GitHub 검색:

    1) Intent Analysis  : Gemini가 쿼리 의도를 파악 → 키워드/topic/awesome 분리
    2) Multi-source     : 일반 키워드 + GitHub Topics + Awesome-list 병렬 검색
    3) Batch Re-ranking : 상위 후보 전체를 Gemini 1회 호출로 재순위
    """
    api_key = os.environ.get("GEMINI_API_KEY") if use_gemini else None

    # ── STEP 1: 의도 분석 ────────────────────────────────────────────────────
    if api_key:
        intent = analyze_intent(user_query, api_key)
    else:
        intent = _fallback_intent(user_query)

    keywords        = intent.get("keywords", [user_query])
    topics          = intent.get("topics", [])
    awesome_kws     = intent.get("awesome_keywords", [])

    # ── STEP 2: 멀티소스 검색 ────────────────────────────────────────────────
    seen_repos: set[str] = set()
    candidates: list[dict] = []

    def _add(repos: list[dict]):
        for r in repos:
            if r["repo"] not in seen_repos:
                seen_repos.add(r["repo"])
                candidates.append(r)

    per_kw = max(3, max_results // max(len(keywords), 1))

    # 2-A: 키워드 검색 — 최대 2개로 제한 (rate limit 보호)
    for kw in keywords[:2]:
        _add(_search_by_keyword(kw, per_page=5))
        if len(candidates) >= max_results * 2:
            break

    # 2-B: GitHub Topics 검색 — 1개만 (정확도 높고 호출 절약)
    for topic in topics[:1]:
        _add(_search_by_topic(topic, per_page=5))

    # 2-C: Awesome-list 검색 — 1개만
    for aw_kw in awesome_kws[:1]:
        _add(_search_awesome_lists(aw_kw, per_page=3))

    if not candidates:
        return [{"error": "GitHub 검색 결과가 없습니다."}]

    # ── STEP 3: README 병렬 수집 (상위 3개만 — API 호출 절약 + 속도 향상) ──
    import concurrent.futures

    pre_sorted   = sorted(candidates, key=lambda r: r["stars"], reverse=True)
    readme_count = min(3, len(pre_sorted)) if api_key else 0  # 3개로 대폭 축소
    top_for_readme = pre_sorted[:readme_count]

    def _fetch_and_assign(repo_dict: dict) -> dict:
        repo_dict["readme"] = _fetch_readme(repo_dict["repo"])
        return repo_dict

    if top_for_readme:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            fetched = list(executor.map(_fetch_and_assign, top_for_readme))
        # candidates 원본에 반영
        readme_map = {r["repo"]: r["readme"] for r in fetched}
        for c in candidates:
            if c["repo"] in readme_map:
                c["readme"] = readme_map[c["repo"]]

    # ── STEP 4: 배치 재순위 ──────────────────────────────────────────────────
    if api_key:
        # readme 있는 상위 15개만 배치 재순위
        top_candidates = sorted(candidates, key=lambda r: r["stars"], reverse=True)[:10]
        rest = [c for c in candidates if c["repo"] not in {r["repo"] for r in top_candidates}]
        top_candidates = _batch_rerank(top_candidates, user_query, api_key)
        # 나머지는 star fallback
        rest = _star_fallback(rest)
        candidates = top_candidates + rest
    else:
        candidates = _star_fallback(candidates)

    # ── STEP 5: 정렬 후 반환 ─────────────────────────────────────────────────
    # awesome-list는 별도 가중치 (큐레이션 신뢰도 반영)
    def sort_key(r: dict):
        base  = r["relevance"]
        bonus = 10 if r.get("is_awesome") else 0
        return (base + bonus, r["stars"])

    candidates.sort(key=sort_key, reverse=True)
    return candidates[:max_results]
