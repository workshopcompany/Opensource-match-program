"""
debug_search.py — 검색 파이프라인 단계별 디버그
실행: python debug_search.py "이족보행 로봇 시뮬레이션"
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error

QUERY = sys.argv[1] if len(sys.argv) > 1 else "bipedal robot simulation"
GITHUB_API = "https://api.github.com"

print(f"\n{'='*60}")
print(f"DEBUG: query = '{QUERY}'")
print(f"GEMINI_API_KEY : {'✅ 있음' if os.environ.get('GEMINI_API_KEY') else '❌ 없음'}")
print(f"GITHUB_TOKEN   : {'✅ 있음' if os.environ.get('GITHUB_TOKEN') else '❌ 없음 (10 req/min)'}")
print(f"{'='*60}\n")

# ── STEP 1: 인터넷 연결 확인 ─────────────────────────────────────────────────
print("[1] 인터넷 연결 테스트...")
try:
    req = urllib.request.Request(
        "https://api.github.com",
        headers={"User-Agent": "debug/1.0", "Accept": "application/vnd.github.v3+json"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        print(f"    ✅ GitHub API 연결 성공 (status {r.status})\n")
except Exception as e:
    print(f"    ❌ GitHub API 연결 실패: {e}")
    print("    → 네트워크 문제입니다. VPN이나 방화벽을 확인하세요.\n")
    sys.exit(1)

# ── STEP 2: GitHub 키워드 검색 (한국어 그대로) ──────────────────────────────
print(f"[2] GitHub 검색 (원본 쿼리: '{QUERY}')...")
try:
    params = urllib.parse.urlencode({"q": QUERY, "sort": "stars", "order": "desc", "per_page": 3})
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "OpenSourceMatchmaker/debug",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(f"{GITHUB_API}/search/repositories?{params}", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    items = data.get("items", [])
    print(f"    결과: {data.get('total_count', 0)}개 (상위 {len(items)}개 표시)")
    for it in items:
        print(f"    - {it['full_name']} ★{it['stargazers_count']}")
    if not items:
        print("    ⚠️  한국어 검색 결과 없음 → 영어 키워드 필요")
    print()
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"    ❌ HTTP {e.code}: {body[:200]}\n")
    if e.code == 403:
        print("    → Rate limit 초과. GITHUB_TOKEN 환경변수를 설정하세요.\n")
    sys.exit(1)

# ── STEP 3: GitHub 검색 (영어 키워드) ────────────────────────────────────────
EN_QUERY = "bipedal robot simulation"
print(f"[3] GitHub 검색 (영어 키워드: '{EN_QUERY}')...")
try:
    time.sleep(6)  # rate limit 보호
    params = urllib.parse.urlencode({"q": EN_QUERY, "sort": "stars", "order": "desc", "per_page": 5})
    req = urllib.request.Request(f"{GITHUB_API}/search/repositories?{params}", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    items = data.get("items", [])
    print(f"    결과: {data.get('total_count', 0)}개 (상위 {len(items)}개 표시)")
    for it in items:
        print(f"    - {it['full_name']} ★{it['stargazers_count']}")
    print()
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"    ❌ HTTP {e.code}: {body[:200]}\n")

# ── STEP 4: GitHub Topic 검색 ─────────────────────────────────────────────────
print("[4] GitHub Topic 검색 (topic:bipedal-robot)...")
try:
    time.sleep(6)
    params = urllib.parse.urlencode({"q": "topic:bipedal-robot", "sort": "stars", "per_page": 3})
    req = urllib.request.Request(f"{GITHUB_API}/search/repositories?{params}", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    items = data.get("items", [])
    print(f"    결과: {len(items)}개")
    for it in items:
        print(f"    - {it['full_name']} ★{it['stargazers_count']}")
    print()
except urllib.error.HTTPError as e:
    print(f"    ❌ HTTP {e.code}\n")

# ── STEP 5: Gemini 테스트 (키 있을 때만) ─────────────────────────────────────
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    print("[5] Gemini analyze_intent 테스트...")
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.0-flash:generateContent?key={api_key}")
        payload = json.dumps({
            "contents": [{"parts": [{"text": f'Translate to English search keywords: "{QUERY}". Output only a JSON array of strings.'}]}],
            "generationConfig": {"maxOutputTokens": 100},
        }).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        print(f"    ✅ Gemini 응답: {text[:200]}")
    except Exception as e:
        print(f"    ❌ Gemini 오류: {e}")
    print()
else:
    print("[5] Gemini 키 없음 → 스킵 (한국어 쿼리가 영어로 변환되지 않아 검색 품질 저하)\n")

# ── STEP 6: Reddit 테스트 ─────────────────────────────────────────────────────
print("[6] Reddit 검색 테스트...")
try:
    params = urllib.parse.urlencode({"q": EN_QUERY, "limit": 3, "sort": "relevance", "t": "year"})
    req = urllib.request.Request(
        f"https://www.reddit.com/search.json?{params}",
        headers={"User-Agent": "debug/1.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    posts = data.get("data", {}).get("children", [])
    print(f"    결과: {len(posts)}개")
    for p in posts:
        print(f"    - [{p['data'].get('subreddit_name_prefixed','')}] {p['data'].get('title','')[:60]}")
    print()
except Exception as e:
    print(f"    ❌ Reddit 오류: {e}\n")

print("="*60)
print("디버그 완료. 위 결과를 공유해주시면 정확한 원인을 찾을 수 있어요.")
print("="*60)
