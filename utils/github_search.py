"""
GitHub Search API — 무료, 인증 없이 10 req/min
GITHUB_TOKEN 환경변수 설정 시 30 req/min으로 상향

Gemini 연동:
  1) 사용자 질문(한국어 포함) → 영어 GitHub 검색 키워드 3~5개로 변환
  2) 검색된 저장소 README를 읽고 적합도(0~100) + 한줄 요약 생성
"""
import os
import json
import time
import re
import urllib.request
import urllib.parse
import urllib.error

GITHUB_API = "https://api.github.com"
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite"]
GEMINI_DELAY  = 5  # 무료 티어 Rate Limit 보호

_last_gh_call:     float = 0.0
_last_gemini_call: float = 0.0


# ── Gemini 호출 공통 ──────────────────────────────────────────────────────────
def _call_gemini(prompt: str, api_key: str, max_tokens: int = 500) -> str | None:
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
                continue   # 다음 모델로 폴백
            return None
        except Exception:
            return None
    return None


# ── STEP 1: 쿼리 → 영어 GitHub 키워드 변환 ───────────────────────────────────
def expand_query(user_query: str, api_key: str | None) -> list[str]:
    """
    Gemini가 있으면: 한국어/자연어 질문을 GitHub 검색에 최적화된 영어 키워드 3~5개로 변환
    없으면: 원본 쿼리를 공백 기준으로 분리해 그대로 사용
    """
    if not api_key:
        return [user_query]

    prompt = f"""You are a GitHub search query optimizer.

Convert the following user query into 3-5 English GitHub search keyword phrases
that will find the most relevant open-source repositories.

Rules:
- Output ONLY a JSON array of strings, no explanation
- Each phrase should be 2-4 words max
- Focus on technical terms, library names, algorithms
- Include both specific and broader terms
- If the query is in Korean, translate and expand appropriately

User query: "{user_query}"

Example output: ["bipedal balance control", "biped walking PID", "humanoid locomotion PyBullet", "bipedal robot simulation"]

Output:"""

    raw = _call_gemini(prompt, api_key, max_tokens=200)
    if not raw:
        return [user_query]
    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        keywords = json.loads(raw)
        if isinstance(keywords, list) and keywords:
            return keywords[:5]
    except Exception:
        pass
    return [user_query]


# ── GitHub API 공통 요청 ──────────────────────────────────────────────────────
def _gh_request(url: str) -> dict | None:
    global _last_gh_call
    elapsed = time.time() - _last_gh_call
    if elapsed < 6:
        time.sleep(6 - elapsed)

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpenSourceMatchmaker/1.0",
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


# ── STEP 2: GitHub 검색 ───────────────────────────────────────────────────────
def _search_repos(keyword: str, per_page: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": keyword,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    })
    data = _gh_request(f"{GITHUB_API}/search/repositories?{params}")
    if not data or "_error" in data:
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
            "source":  "github",
            "readme":  "",
            "gemini_summary": "",
            "relevance": 0,
        })
    return results


# ── STEP 3: README 가져오기 ───────────────────────────────────────────────────
def _fetch_readme(repo_full_name: str) -> str:
    data = _gh_request(
        f"{GITHUB_API}/repos/{repo_full_name}/readme"
    )
    if not data or "_error" in data:
        return ""
    # base64 디코딩
    import base64
    content = data.get("content", "")
    encoding = data.get("encoding", "")
    if encoding == "base64":
        try:
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
            return decoded[:3000]  # 앞 3000자만
        except Exception:
            return ""
    return content[:3000]


# ── STEP 4: Gemini로 적합도 판단 + 한줄 요약 ─────────────────────────────────
def _evaluate_repo(repo: dict, user_query: str, api_key: str) -> dict:
    readme_snippet = repo.get("readme", "")[:2000]
    description    = repo.get("summary", "")
    topics         = ", ".join(repo.get("topics", []))

    prompt = f"""You are evaluating whether a GitHub repository matches a user's need.

User's need (may be in Korean): "{user_query}"

Repository: {repo['repo']}
Description: {description}
Topics: {topics}
README (first 2000 chars):
\"\"\"
{readme_snippet}
\"\"\"

Output ONLY a JSON object (no markdown):
{{
  "relevance": 0-100,
  "reason": "한 줄 적합 이유 (한국어, 30자 이내)",
  "summary_ko": "이 앱은 ...을 해주는 무료 도구입니다 (한국어, 50자 이내)"
}}"""

    raw = _call_gemini(prompt, api_key, max_tokens=200)
    if not raw:
        return repo

    try:
        raw = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        repo["relevance"]      = result.get("relevance", 0)
        repo["reason"]         = result.get("reason", "")
        repo["gemini_summary"] = result.get("summary_ko", repo["summary"])
    except Exception:
        pass
    return repo


# ── 메인 함수 ─────────────────────────────────────────────────────────────────
def search_github(
    user_query: str,
    max_results: int = 8,
    use_gemini: bool = True,
) -> list[dict]:
    """
    1) Gemini로 쿼리 확장 (한국어 → 영어 키워드)
    2) 키워드별 GitHub 검색 (중복 제거)
    3) README 가져오기
    4) Gemini로 적합도 평가 + 한국어 요약
    5) 적합도 순 정렬
    """
    api_key = os.environ.get("GEMINI_API_KEY") if use_gemini else None

    # STEP 1: 쿼리 확장
    keywords = expand_query(user_query, api_key)

    # STEP 2: 각 키워드로 검색 (중복 제거)
    seen_repos: set[str] = set()
    candidates: list[dict] = []
    per_kw = max(3, max_results // len(keywords))

    for kw in keywords:
        repos = _search_repos(kw, per_page=per_kw)
        for r in repos:
            if r["repo"] not in seen_repos:
                seen_repos.add(r["repo"])
                candidates.append(r)
        if len(candidates) >= max_results * 2:
            break

    if not candidates:
        return [{"error": "GitHub 검색 결과가 없습니다."}]

    # STEP 3 & 4: README + Gemini 평가 (상위 후보만, API 절약)
    evaluate_count = min(6, len(candidates)) if api_key else 0

    for i, repo in enumerate(candidates[:evaluate_count]):
        # README 가져오기
        readme = _fetch_readme(repo["repo"])
        candidates[i]["readme"] = readme
        # Gemini 적합도 평가
        candidates[i] = _evaluate_repo(candidates[i], user_query, api_key)

    # 나머지는 별점을 적합도 대신 사용
    for i in range(evaluate_count, len(candidates)):
        candidates[i]["relevance"] = min(50, candidates[i]["stars"] // 10)
        candidates[i]["gemini_summary"] = candidates[i]["summary"]
        candidates[i]["reason"] = "별점 기준 정렬"

    # STEP 5: 적합도 순 정렬
    candidates.sort(key=lambda r: (r["relevance"], r["stars"]), reverse=True)

    return candidates[:max_results]
