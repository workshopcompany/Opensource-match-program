"""
GitHub Search API — 무료, 인증 없이 10 req/min
GITHUB_TOKEN 환경변수 설정 시 30 req/min으로 상향
"""
import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error

GITHUB_API = "https://api.github.com/search/repositories"

# 마지막 호출 시각 (모듈 레벨 rate limit 관리)
_last_call: float = 0.0


def search_github(query: str, max_results: int = 8) -> list[dict]:
    """
    GitHub Search API로 저장소 검색.
    반환: [{"name", "repo", "owner", "summary", "stars", "lang", "url", "topics"}, ...]
    """
    global _last_call

    # Rate limit: 최소 6초 간격 (10 req/min 안전 마진)
    elapsed = time.time() - _last_call
    if elapsed < 6:
        time.sleep(6 - elapsed)

    # 쿼리 구성: streamlit OR python 태그 포함해서 앱 위주로
    q = f"{query} topic:streamlit OR topic:python-app OR topic:open-source"
    params = urllib.parse.urlencode({
        "q": q,
        "sort": "stars",
        "order": "desc",
        "per_page": max_results,
    })
    url = f"{GITHUB_API}?{params}"

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
            data = json.loads(resp.read())
        _last_call = time.time()

        results = []
        for item in data.get("items", []):
            results.append({
                "name":    item.get("name", ""),
                "repo":    item.get("full_name", ""),
                "owner":   item.get("owner", {}).get("login", ""),
                "summary": item.get("description") or "설명 없음",
                "stars":   item.get("stargazers_count", 0),
                "lang":    item.get("language") or "Unknown",
                "url":     item.get("html_url", ""),
                "topics":  item.get("topics", []),
                "updated": item.get("updated_at", "")[:10],
                "source":  "github",
            })
        return results

    except urllib.error.HTTPError as e:
        if e.code == 403:
            return [{"error": "GitHub API rate limit 초과. 잠시 후 다시 시도하세요."}]
        return [{"error": f"GitHub API 오류: {e.code}"}]
    except Exception as e:
        return [{"error": str(e)}]
