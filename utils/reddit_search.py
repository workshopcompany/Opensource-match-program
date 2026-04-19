"""
Reddit 검색 — 공식 JSON API (인증 불필요, 무료)
Reddit은 /search.json 엔드포인트를 공개로 제공합니다.
관련 서브레딧: r/opensource, r/Python, r/MachineLearning, r/robotics, r/engineering
"""
import json
import time
import urllib.request
import urllib.parse
import urllib.error

SUBREDDITS = [
    "opensource",
    "Python",
    "MachineLearning",
    "robotics",
    "engineering",
    "learnmachinelearning",
    "computervision",
    "ArtificialIntelligence",
]

_last_call: float = 0.0
REDDIT_DELAY = 2.0  # Reddit은 2초 간격으로 충분


def search_reddit(query: str, max_results: int = 6) -> list[dict]:
    """
    Reddit JSON API로 관련 포스트 검색.
    반환: [{"title", "url", "subreddit", "score", "summary", "source"}, ...]
    """
    global _last_call

    elapsed = time.time() - _last_call
    if elapsed < REDDIT_DELAY:
        time.sleep(REDDIT_DELAY - elapsed)

    # 여러 서브레딧을 OR로 묶어 검색
    subreddit_str = "+".join(SUBREDDITS[:5])  # 상위 5개
    params = urllib.parse.urlencode({
        "q": query,
        "sort": "relevance",
        "limit": max_results,
        "t": "year",       # 최근 1년 이내
        "restrict_sr": "false",
    })
    url = f"https://www.reddit.com/r/{subreddit_str}/search.json?{params}"

    headers = {
        "User-Agent": "OpenSourceMatchmaker/1.0 (research tool)",
        "Accept": "application/json",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        _last_call = time.time()

        results = []
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            title = p.get("title", "")
            selftext = p.get("selftext", "")
            # 본문 앞 150자를 요약으로
            snippet = selftext[:150].replace("\n", " ").strip() if selftext else "본문 없음"
            results.append({
                "title":     title,
                "url":       f"https://www.reddit.com{p.get('permalink', '')}",
                "subreddit": p.get("subreddit_name_prefixed", ""),
                "score":     p.get("score", 0),
                "summary":   snippet,
                "comments":  p.get("num_comments", 0),
                "created":   p.get("created_utc", 0),
                "source":    "reddit",
            })
        return results

    except urllib.error.HTTPError as e:
        if e.code == 429:
            return [{"error": "Reddit rate limit 초과. 잠시 후 다시 시도하세요."}]
        return [{"error": f"Reddit API 오류: {e.code}"}]
    except Exception as e:
        return [{"error": str(e)}]
