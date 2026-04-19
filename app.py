import os
import time
import streamlit as st
from utils.db import load_db, save_db
from utils.classifier import infer_category, GEMINI_CALL_DELAY
from utils.matcher import semantic_score
from utils.github_fetcher import fetch_repo_info
from utils.github_search import search_github
from utils.reddit_search import search_reddit

# ── 상수 ─────────────────────────────────────────────────────────────────────
GITHUB_USER = "workcompany"
GITHUB_REPO = "opensource-match-program"
GITHUB_URL  = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}"

st.set_page_config(
    page_title="OpenSource App Matchmaker",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── 레이아웃 ── */
.main .block-container { padding-top: 1.5rem; max-width: 900px; }

/* ── 검색창 히어로 ── */
.hero-wrap {
    text-align: center;
    padding: 2.8rem 1rem 1.8rem;
}
.hero-title {
    font-size: 2rem; font-weight: 700; color: #111827;
    letter-spacing: -0.5px; margin-bottom: 0.3rem;
}
.hero-sub {
    font-size: 0.95rem; color: #6b7280; margin-bottom: 1.6rem;
}

/* ── 카드 공통 ── */
.app-card, .gh-card, .rd-card {
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
    margin-bottom: 0.7rem;
}
.app-card { border: 1px solid #e5e7eb; background: white; }
.app-card:hover { border-color: #9ca3af; }
.gh-card  { border: 1px solid #d1fae5; background: #f0fdf4; }
.gh-card.awesome { border: 1px solid #fde68a; background: #fffbeb; }
.rd-card  { border: 1px solid #fee2e2; background: #fff7f7; }

/* ── 점수 바 ── */
.score-bar  { height: 4px; background: #f3f4f6; border-radius: 2px; margin-top: 8px; }
.score-fill { height: 4px; border-radius: 2px; }

/* ── 배지 ── */
.badge      { display:inline-block;font-size:11px;padding:2px 9px;border-radius:20px;font-weight:500;margin-right:4px; }
.badge-eng  { background:#E6F1FB;color:#0C447C; }
.badge-rob  { background:#EEEDFE;color:#3C3489; }
.badge-ai   { background:#E1F5EE;color:#085041; }
.badge-mfg  { background:#FAECE7;color:#712B13; }
.badge-util { background:#FAEEDA;color:#633806; }

/* ── 소스 태그 ── */
.src-gh  { display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;background:#dcfce7;color:#166534;font-weight:500; }
.src-rd  { display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;background:#fee2e2;color:#991b1b;font-weight:500; }
.src-db  { display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;background:#eff6ff;color:#1e40af;font-weight:500; }
.src-aw  { display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;background:#fef3c7;color:#92400e;font-weight:500; }

/* ── 예시 버튼 줄 ── */
div[data-testid="column"] > div > div > div > button {
    font-size: 12px !important;
    padding: 4px 10px !important;
    border-radius: 20px !important;
    background: #f3f4f6 !important;
    color: #374151 !important;
    border: 1px solid #e5e7eb !important;
}
div[data-testid="column"] > div > div > div > button:hover {
    background: #e5e7eb !important;
}
</style>
""", unsafe_allow_html=True)

# ── 카테고리 트리 ─────────────────────────────────────────────────────────────
BADGE_MAP = {
    "Engineering": "badge-eng", "Robotics": "badge-rob",
    "AI / ML": "badge-ai",     "Manufacturing": "badge-mfg",
    "Utility": "badge-util",
}
CAT_TREE = {
    "Engineering": {
        "Manufacturing":    ["MIM / Powder Metallurgy", "Mold Design", "CNC / Machining"],
        "CFD / Simulation": ["OpenFOAM", "FEA", "Thermal Analysis"],
        "Materials Science":["Shrinkage Prediction", "Phase Diagram", "Alloy Design"],
    },
    "Robotics": {
        "Locomotion Control": ["Bipedal Walking", "Quadruped Gait", "Wheeled Navigation"],
        "Simulation":         ["PyBullet", "MuJoCo", "ROS Integration"],
        "Perception":         ["SLAM", "Object Detection", "Sensor Fusion"],
    },
    "AI / ML": {
        "NLP":            ["LLM Wrapper", "RAG Pipeline", "Text Classification"],
        "Automation":     ["LangChain", "Workflow", "Zapier Integration"],
        "Computer Vision":["Image Segmentation", "Pose Estimation"],
    },
    "Utility": {
        "Data Tools": ["File Converter", "Scraper", "Dashboard"],
        "DevOps":     ["GitHub Actions", "CI/CD", "Monitoring"],
    },
}

EXAMPLE_QUERIES = [
    "이족보행 균형 제어", "MIM 수축률 예측",
    "OpenFOAM 유동 해석", "RAG pipeline python",
    "로봇 시뮬레이션 MuJoCo", "몰드 설계 최적화",
]

# ── 세션 상태 초기화 ─────────────────────────────────────────────────────────
for _k, _v in {
    "last_api_call": 0.0,
    "analyze_result": None,
    "search_results": {},
    "last_query": "",
    "trigger_search": False,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── 유틸 ─────────────────────────────────────────────────────────────────────
def cooldown_remaining() -> float:
    return max(0.0, GEMINI_CALL_DELAY - (time.time() - st.session_state.last_api_call))


# ── 카드 렌더러 ───────────────────────────────────────────────────────────────
def render_card(app: dict, score: int | None = None):
    bc = BADGE_MAP.get(app.get("cat_major", ""), "badge-util")
    tags_html = "".join(
        f'<span style="font-size:10px;padding:2px 6px;border-radius:10px;'
        f'background:#f3f4f6;color:#6b7280;margin-right:3px">{t}</span>'
        for t in app.get("tags", [])[:5]
    )
    if score is not None:
        pct         = min(100, score * 4)
        score_html  = f'<div class="score-bar"><div class="score-fill" style="width:{pct}%;background:#111827"></div></div>'
        score_right = (f'<span style="font-size:18px;font-weight:500">{score}</span>'
                       f'<span style="font-size:11px;color:#9ca3af"> pts</span>')
    else:
        score_html  = ""
        score_right = f'<span style="font-size:12px;color:#9ca3af">★ {app.get("stars", 0)}</span>'

    repo      = app.get("repo", "")
    repo_link = (
        f'<a href="https://github.com/{repo}" target="_blank" '
        f'style="font-size:12px;color:#6b7280;text-decoration:none">{repo} ↗</a>'
    ) if repo else ""

    st.markdown(f"""
    <div class="app-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
        <div>
          <span class="src-db">내 DB</span>&nbsp;
          <span style="font-size:14px;font-weight:500;color:#111827">{app["name"]}</span>
          <div style="margin-top:3px">{repo_link}</div>
        </div>
        <div style="text-align:right">{score_right}
          <div style="margin-top:3px"><span class="badge {bc}">{app.get("cat_major","")}</span></div>
        </div>
      </div>
      <div style="font-size:13px;color:#4b5563;line-height:1.6;margin-bottom:8px">{app["summary"]}</div>
      <div style="font-size:11px;color:#9ca3af;margin-bottom:6px">
        {app.get("cat_major","")} › {app.get("cat_mid","")} › {app.get("cat_minor","")}
      </div>
      {tags_html}{score_html}
    </div>
    """, unsafe_allow_html=True)


def render_github_card(item: dict):
    is_awesome   = item.get("is_awesome", False)
    card_class   = "gh-card awesome" if is_awesome else "gh-card"
    src_tag      = '<span class="src-aw">⭐ Awesome List</span>' if is_awesome else '<span class="src-gh">GitHub</span>'
    topics_html  = "".join(
        f'<span style="font-size:10px;padding:1px 7px;border-radius:10px;'
        f'background:#dcfce7;color:#166534;margin-right:3px">{t}</span>'
        for t in item.get("topics", [])[:6]
    )
    relevance   = item.get("relevance", 0)
    rel_color   = "#16a34a" if relevance >= 70 else "#d97706" if relevance >= 40 else "#9ca3af"
    rel_label   = f'<span style="font-size:11px;font-weight:600;color:{rel_color}">적합도 {relevance}%</span>' if relevance else ""
    reason      = item.get("reason", "")
    reason_html = f'<div style="font-size:11px;color:#6b7280;margin-top:3px">💡 {reason}</div>' if reason else ""
    display_sum = item.get("gemini_summary") or item.get("summary") or "설명 없음"
    pct         = min(100, relevance)
    bar_html    = (f'<div style="height:3px;background:#f3f4f6;border-radius:2px;margin-top:8px">'
                   f'<div style="width:{pct}%;height:3px;background:{rel_color};border-radius:2px"></div>'
                   f'</div>') if relevance else ""
    search_src  = item.get("search_source", "")
    src_hint    = {"topic": "topic 검색", "awesome": "awesome-list", "keyword": "키워드 검색"}.get(search_src, "")
    src_hint_html = (f'<span style="font-size:10px;color:#9ca3af;margin-left:6px">{src_hint}</span>'
                     ) if src_hint else ""

    st.markdown(f"""
    <div class="{card_class}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:5px">
        <div>
          {src_tag}{src_hint_html}&nbsp;
          <a href="{item['url']}" target="_blank"
             style="font-size:14px;font-weight:500;color:#111827;text-decoration:none">
            {item['repo']} ↗
          </a>
          {reason_html}
        </div>
        <div style="text-align:right">
          {rel_label}
          <div style="font-size:11px;color:#9ca3af">★ {item['stars']} · {item.get('lang','')}</div>
          <div style="font-size:10px;color:#9ca3af">🍴 {item.get('forks',0)}</div>
        </div>
      </div>
      <div style="font-size:13px;color:#374151;line-height:1.5;margin-bottom:8px">{display_sum}</div>
      <div style="font-size:11px;color:#9ca3af;margin-bottom:5px">최근 커밋: {item.get('pushed', item.get('updated',''))}</div>
      {topics_html}
      {bar_html}
    </div>
    """, unsafe_allow_html=True)


def render_reddit_card(item: dict):
    relevance    = item.get("relevance", 0)
    rel_color    = "#dc2626" if relevance >= 60 else "#9ca3af"
    rel_label    = f'<span style="font-size:11px;font-weight:600;color:{rel_color}">관련도 {relevance}%</span>' if relevance else ""
    searched_as  = item.get("searched_as", "")
    searched_html = (f'<div style="font-size:10px;color:#9ca3af;margin-bottom:4px">'
                     f'🔍 "{searched_as}" 로 검색됨</div>') if searched_as else ""

    st.markdown(f"""
    <div class="rd-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:5px">
        <div>
          <span class="src-rd">Reddit</span>&nbsp;
          <span style="font-size:11px;color:#9ca3af">{item.get('subreddit','')}</span>
        </div>
        <div style="text-align:right">
          {rel_label}
          <div style="font-size:11px;color:#9ca3af">👍 {item.get('score',0)} · 💬 {item.get('comments',0)}</div>
        </div>
      </div>
      {searched_html}
      <a href="{item['url']}" target="_blank"
         style="font-size:13px;font-weight:500;color:#111827;text-decoration:none;line-height:1.5">
        {item['title']} ↗
      </a>
      <div style="font-size:12px;color:#6b7280;margin-top:5px;line-height:1.5">{item.get('summary','')}</div>
    </div>
    """, unsafe_allow_html=True)


# ── 사이드바 ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 App Matchmaker")
    st.caption("오픈소스 무료 앱을 찾고 등록하세요")
    st.markdown(f"[📂 GitHub 저장소]({GITHUB_URL})")
    st.divider()
    page = st.radio(
        "메뉴",
        ["🏠 홈 & 검색", "➕ 저장소 등록", "📂 카테고리 탐색", "📋 전체 목록"],
        label_visibility="collapsed",
    )
    st.divider()
    db = load_db()
    st.metric("등록된 앱", len(db))
    cats: dict[str, int] = {}
    for _a in db:
        cats[_a["cat_major"]] = cats.get(_a["cat_major"], 0) + 1
    for _c, _n in cats.items():
        st.caption(f"• {_c}: {_n}개")

    st.divider()
    has_gemini   = bool(os.environ.get("GEMINI_API_KEY"))
    has_gh_token = bool(os.environ.get("GITHUB_TOKEN"))
    rem = cooldown_remaining()
    st.caption("**API 상태**")
    if has_gemini:
        st.caption(f"{'⏳' if rem > 0 else '✅'} Gemini {'쿨다운 ' + str(int(rem)) + '초' if rem > 0 else '준비됨'}")
    else:
        st.caption("⚠️ Gemini 키 없음")
    st.caption(f"{'🔑' if has_gh_token else '🔓'} GitHub {'토큰 인증' if has_gh_token else '비인증 (10 req/min)'}")
    st.caption("🟠 Reddit 공개 API")

db = load_db()

# ═══════════════════════════════════════════════════════════════════════════════
# 🏠 홈 & 검색 (메인 페이지 — 검색창 중심)
# ═══════════════════════════════════════════════════════════════════════════════
if page == "🏠 홈 & 검색":

    # ── 히어로 헤더 ──────────────────────────────────────────────────────────
    st.markdown("""
    <div class="hero-wrap">
      <div class="hero-title">🔍 OpenSource App Matchmaker</div>
      <div class="hero-sub">GitHub · Reddit · 내 DB — 3가지 소스에서 오픈소스를 찾아드립니다</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 검색창 ───────────────────────────────────────────────────────────────
    query = st.text_input(
        label="search",
        placeholder="찾고 싶은 앱을 자연어로 설명하세요  예) 이족보행 로봇 균형 제어 파이썬",
        label_visibility="collapsed",
    )

    # ── 예시 쿼리 버튼 ───────────────────────────────────────────────────────
    cols = st.columns(len(EXAMPLE_QUERIES))
    for i, eq in enumerate(EXAMPLE_QUERIES):
        if cols[i].button(eq, key=f"eq_{i}"):
            query = eq
            st.session_state.trigger_search = True

    # ── 검색 옵션 + 버튼 ─────────────────────────────────────────────────────
    col_btn, col_gh, col_rd = st.columns([2, 2, 2])
    with col_btn:
        do_search = st.button("🔍 검색", type="primary", use_container_width=True)
    with col_gh:
        use_github = st.checkbox("GitHub 포함", value=True)
    with col_rd:
        use_reddit = st.checkbox("Reddit 포함", value=True)

    # 예시 버튼 클릭 시 자동 검색 트리거
    if st.session_state.trigger_search and query:
        do_search = True
        st.session_state.trigger_search = False

    # 쿼리 변경 시 캐시 초기화
    if query != st.session_state.last_query:
        st.session_state.search_results = {}
        st.session_state.last_query = query

    # ── 검색 실행 ────────────────────────────────────────────────────────────
    if do_search and query:
        with st.spinner("3가지 소스에서 검색 중..."):
            db_scored  = sorted(db, key=lambda a: semantic_score(a, query), reverse=True)
            gh_results = search_github(query, max_results=10,
                                       use_gemini=bool(os.environ.get("GEMINI_API_KEY"))
                                       ) if use_github else []
            rd_results = search_reddit(query, max_results=8) if use_reddit else []

        st.session_state.search_results = {
            "db": db_scored, "github": gh_results,
            "reddit": rd_results, "query": query,
        }

    # ── 결과 표시 ────────────────────────────────────────────────────────────
    cached = st.session_state.search_results
    if cached:
        db_scored  = cached.get("db", [])
        gh_results = cached.get("github", [])
        rd_results = cached.get("reddit", [])
        q_label    = cached.get("query", query)

        gh_ok = [r for r in gh_results if "error" not in r]
        rd_ok = [r for r in rd_results if "error" not in r]
        db_ok = [a for a in db_scored if semantic_score(a, q_label) > 0]

        # ── 탭 ───────────────────────────────────────────────────────────────
        tab_gh, tab_rd, tab_db = st.tabs([
            f"🐙 GitHub ({len(gh_ok)}개)",
            f"🟠 Reddit ({len(rd_ok)}개)",
            f"📋 내 DB ({len(db_ok)}개)",
        ])

        # ── GitHub 탭 ────────────────────────────────────────────────────────
        with tab_gh:
            if not use_github:
                st.info("GitHub Search가 비활성화되어 있습니다.")
            elif not gh_ok:
                err = gh_results[0].get("error", "결과 없음") if gh_results else "결과 없음"
                st.warning(f"GitHub 검색 결과 없음: {err}")
            else:
                has_gemini_key = bool(os.environ.get("GEMINI_API_KEY"))
                awesome_count  = sum(1 for r in gh_ok if r.get("is_awesome"))
                topic_count    = sum(1 for r in gh_ok if r.get("search_source") == "topic")
                st.caption(
                    f"{'🤖 Gemini 쿼리 확장 · ' if has_gemini_key else ''}"
                    f"키워드 · Topic · Awesome-list 3중 검색 — "
                    f"저장소 **{len(gh_ok)}개** 발견 "
                    f"(Awesome {awesome_count}개 · Topic태그 {topic_count}개 포함)"
                )
                for item in gh_ok:
                    render_github_card(item)
                    if not any(a["repo"] == item["repo"] for a in db):
                        if st.button(f"+ DB에 등록", key=f"gh_add_{item['repo']}"):
                            with st.spinner("분석 중..."):
                                info = fetch_repo_info(item["repo"])
                                cat  = infer_category(info["content"], item["repo"])
                                st.session_state.last_api_call = time.time()
                            db.append({
                                "id": len(db) + 1,
                                "name": info["name"], "repo": item["repo"],
                                "owner": item["owner"], "summary": cat["summary"],
                                "cat_major": cat["major"], "cat_mid": cat["mid"],
                                "cat_minor": cat["minor"],
                                "lang": item.get("lang", "Python"),
                                "stars": item.get("stars", 0),
                                "tags": cat.get("tags", []) + item.get("topics", [])[:3],
                                "has_readme": info.get("has_readme", False),
                            })
                            save_db(db)
                            st.success(f"'{info['name']}' 등록 완료!")
                            st.rerun()

        # ── Reddit 탭 ────────────────────────────────────────────────────────
        with tab_rd:
            if not use_reddit:
                st.info("Reddit 검색이 비활성화되어 있습니다.")
            elif not rd_ok:
                err = rd_results[0].get("error", "결과 없음") if rd_results else "결과 없음"
                st.warning(f"Reddit 검색 결과 없음: {err}")
            else:
                searched_as = rd_ok[0].get("searched_as", "") if rd_ok else ""
                st.caption(
                    f"{'🤖 영어로 번역 후 검색: **' + searched_as + '** · ' if searched_as else ''}"
                    f"전체 Reddit + 도메인 전문 서브레딧 — 포스트 **{len(rd_ok)}개** 발견"
                )
                for item in rd_ok:
                    render_reddit_card(item)

        # ── 내 DB 탭 ─────────────────────────────────────────────────────────
        with tab_db:
            if not db_ok:
                st.info("DB에 매칭되는 앱이 없습니다. GitHub 탭에서 등록해 보세요.")
            for app in db_ok:
                render_card(app, score=semantic_score(app, q_label))

    elif not query:
        # 검색 전 — 최근 등록 앱 미리보기
        st.divider()
        st.caption("최근 등록된 앱")
        for app in list(reversed(db))[:3]:
            render_card(app)

# ═══════════════════════════════════════════════════════════════════════════════
# ➕ 저장소 등록
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "➕ 저장소 등록":
    st.title("➕ 저장소 / 앱 등록")
    tab1, tab2 = st.tabs(["GitHub 저장소 URL", "직접 입력"])

    with tab1:
        repo_input = st.text_input("저장소", placeholder=f"예: {GITHUB_USER}/{GITHUB_REPO}")
        rem = cooldown_remaining()
        if rem > 0:
            st.info(f"⏳ Gemini 쿨다운 — {rem:.0f}초 후 분석 가능")

        if st.button("🔍 분석 시작", type="primary", disabled=rem > 0):
            if repo_input:
                st.session_state.analyze_result = None
                with st.spinner("README / 코드 가져오는 중..."):
                    info = fetch_repo_info(repo_input)
                with st.spinner(f"Gemini 분류 중... (최대 {GEMINI_CALL_DELAY + 10}초)"):
                    cat = infer_category(info["content"], repo_input)
                    st.session_state.last_api_call = time.time()
                st.session_state.analyze_result = {"info": info, "cat": cat, "repo": repo_input}

        res = st.session_state.analyze_result
        if res:
            info, cat, repo_cached = res["info"], res["cat"], res["repo"]
            model_used = cat.get("_model_used", "keyword")
            st.success(f"분석 완료! (모델: `{model_used}`)")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**앱 이름:** {info['name']}")
                st.markdown(f"**언어:** {info.get('lang','Python')} · ★ {info.get('stars',0)}")
                st.markdown(f"**README:** {'✅ 있음' if info.get('has_readme') else '❌ 없음 (코드 분석)'}")
                st.markdown(f"**설명:** {cat['summary']}")
            with c2:
                st.markdown(f"**대분류:** {cat['major']}")
                st.markdown(f"**중분류:** {cat['mid']}")
                st.markdown(f"**소분류:** {cat['minor']}")
                st.progress(cat["confidence"] / 100, text=f"신뢰도 {cat['confidence']}%")

            if model_used == "gemini-2.0-flash-lite":
                st.info("ℹ️ gemini-2.0-flash 할당량 초과 → lite 모델로 폴백")
            elif model_used == "exhausted":
                st.warning("⚠️ 모든 Gemini 모델 할당량 초과. 키워드 분류 결과입니다.")

            if any(a["repo"] == repo_cached for a in db):
                st.warning("이미 등록된 저장소입니다.")
            elif st.button("✅ DB에 등록", type="primary"):
                db.append({
                    "id": len(db) + 1, "name": info["name"], "repo": repo_cached,
                    "owner": repo_cached.split("/")[0], "summary": cat["summary"],
                    "cat_major": cat["major"], "cat_mid": cat["mid"], "cat_minor": cat["minor"],
                    "lang": info.get("lang", "Python"), "stars": info.get("stars", 0),
                    "tags": cat.get("tags", []), "has_readme": info.get("has_readme", False),
                })
                save_db(db)
                st.session_state.analyze_result = None
                st.success(f"'{info['name']}' 등록 완료!")
                st.rerun()

    with tab2:
        with st.form("manual"):
            name     = st.text_input("앱 이름 *")
            repo     = st.text_input("GitHub 저장소 (선택)", placeholder="owner/repo")
            summary  = st.text_area("앱 설명 *")
            c1, c2, c3 = st.columns(3)
            major    = c1.selectbox("대분류", list(CAT_TREE.keys()) + ["Other"])
            mid      = c2.text_input("중분류")
            minor    = c3.text_input("소분류")
            lang     = st.selectbox("언어", ["Python", "JavaScript", "TypeScript", "Other"])
            tags_raw = st.text_input("태그 (쉼표 구분)")
            if st.form_submit_button("등록", type="primary") and name and summary:
                db.append({
                    "id": len(db) + 1, "name": name, "repo": repo,
                    "owner": repo.split("/")[0] if "/" in repo else "",
                    "summary": summary, "cat_major": major, "cat_mid": mid, "cat_minor": minor,
                    "lang": lang, "stars": 0,
                    "tags": [t.strip() for t in tags_raw.split(",") if t.strip()],
                    "has_readme": False,
                })
                save_db(db)
                st.success(f"'{name}' 등록 완료!")
                st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# 📂 카테고리 탐색
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📂 카테고리 탐색":
    st.title("📂 카테고리 탐색")
    sel_major = st.selectbox("대분류", ["전체"] + list(CAT_TREE.keys()))

    if sel_major == "전체":
        cols = st.columns(2)
        for i, (cat, subs) in enumerate(CAT_TREE.items()):
            cnt = sum(1 for a in db if a["cat_major"] == cat)
            with cols[i % 2]:
                st.markdown(f"**{cat}** — 앱 {cnt}개")
                for m in subs:
                    mc = sum(1 for a in db if a["cat_mid"] == m)
                    st.caption(f"  • {m} ({mc})")
    else:
        subs    = CAT_TREE[sel_major]
        sel_mid = st.selectbox("중분류", ["전체"] + list(subs.keys()))
        if sel_mid != "전체":
            st.caption("소분류: " + " · ".join(subs[sel_mid]))
        filtered = [a for a in db if a["cat_major"] == sel_major]
        if sel_mid != "전체":
            filtered = [a for a in filtered if a["cat_mid"] == sel_mid]
        st.caption(f"{len(filtered)}개 앱")
        for app in filtered:
            render_card(app)
        if not filtered:
            st.info("아직 등록된 앱이 없습니다.")

# ═══════════════════════════════════════════════════════════════════════════════
# 📋 전체 목록
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📋 전체 목록":
    st.title("📋 전체 등록 앱")
    sort_by = st.selectbox("정렬", ["등록 순 (최신)", "별점 순", "이름 순"])
    if sort_by == "별점 순":
        db_s = sorted(db, key=lambda a: a.get("stars", 0), reverse=True)
    elif sort_by == "이름 순":
        db_s = sorted(db, key=lambda a: a["name"])
    else:
        db_s = list(reversed(db))
    st.caption(f"총 {len(db_s)}개")
    for app in db_s:
        render_card(app)
