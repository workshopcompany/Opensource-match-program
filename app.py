import os
import time
import streamlit as st
import streamlit.components.v1
from utils.db import load_db, save_db
from utils.classifier import infer_category, GEMINI_CALL_DELAY
from utils.matcher import semantic_score
from utils.github_fetcher import fetch_repo_info
from utils.github_search import search_github
from utils.reddit_search import search_reddit
from utils.query_expander import build_plan, quality_filter, deduplicate, QUALITY_PRESETS
from utils.huggingface_search import search_huggingface

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


# ── TXT 다운로드 생성 ─────────────────────────────────────────────────────────
def _results_to_txt(query: str, gh_ok: list, rd_ok: list, db_ok: list, hf_ok: list | None = None) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append(f"OpenSource App Matchmaker — 검색 결과")
    lines.append(f"검색어: {query}")
    import datetime
    lines.append(f"날짜: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)

    if gh_ok:
        lines.append(f"\n[GitHub — {len(gh_ok)}개]")
        lines.append("-" * 40)
        for i, r in enumerate(gh_ok, 1):
            lines.append(f"{i}. {r['repo']}")
            lines.append(f"   ★ {r.get('stars', 0)}  |  {r.get('lang', '')}  |  forks: {r.get('forks', 0)}")
            summary = r.get('gemini_summary') or r.get('summary') or ''
            if summary:
                lines.append(f"   {summary}")
            reason = r.get('reason', '')
            if reason:
                lines.append(f"   💡 {reason}")
            lines.append(f"   🔗 {r.get('url', '')}")
            lines.append("")

    if rd_ok:
        lines.append(f"\n[Reddit — {len(rd_ok)}개]")
        lines.append("-" * 40)
        for i, r in enumerate(rd_ok, 1):
            lines.append(f"{i}. {r.get('title', '')}")
            lines.append(f"   {r.get('subreddit', '')}  |  👍 {r.get('score', 0)}  |  💬 {r.get('comments', 0)}")
            summary = r.get('summary', '')
            if summary and summary != "본문 없음":
                lines.append(f"   {summary[:120]}")
            lines.append(f"   🔗 {r.get('url', '')}")
            lines.append("")

    if db_ok:
        lines.append(f"\n[내 DB — {len(db_ok)}개]")
        lines.append("-" * 40)
        for i, a in enumerate(db_ok, 1):
            lines.append(f"{i}. {a['name']}")
            lines.append(f"   {a.get('cat_major','')} › {a.get('cat_mid','')} › {a.get('cat_minor','')}")
            lines.append(f"   {a.get('summary','')}")
            repo = a.get('repo', '')
            if repo:
                lines.append(f"   🔗 https://github.com/{repo}")
            lines.append("")

    if hf_ok:
        lines.append(f"\n[HuggingFace — {len(hf_ok)}개]")
        lines.append("-" * 40)
        for i, r in enumerate(hf_ok, 1):
            kind = "Space" if r.get("type") == "space" else "Model"
            lines.append(f"{i}. [{kind}] {r.get('id', '')}")
            lines.append(f"   ❤️ {r.get('likes_fmt','0')} likes  |  {r.get('pipeline_ko') or r.get('sdk','')}")
            if r.get("summary"):
                lines.append(f"   {r['summary'][:120]}")
            lines.append(f"   🔗 {r.get('url', '')}")
            lines.append("")

    lines.append("=" * 60)
    lines.append("generated by OpenSource App Matchmaker")
    return "\n".join(lines)



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
    import html as _html
    is_awesome  = item.get("is_awesome", False)
    bg_color    = "#fffbeb" if is_awesome else "#f0fdf4"
    border_color= "#fde68a" if is_awesome else "#d1fae5"
    src_label   = "⭐ Awesome List" if is_awesome else "GitHub"
    src_bg      = "#fef3c7" if is_awesome else "#dcfce7"
    src_fg      = "#92400e" if is_awesome else "#166534"

    relevance  = item.get("relevance", 0)
    rel_color  = "#16a34a" if relevance >= 70 else "#d97706" if relevance >= 40 else "#9ca3af"
    rel_html   = f'<span style="font-size:11px;font-weight:600;color:{rel_color}">적합도 {relevance}%</span>' if relevance else ""
    reason     = _html.escape(item.get("reason", ""))
    reason_html= f'<div style="font-size:11px;color:#6b7280;margin-top:3px">💡 {reason}</div>' if reason else ""
    display_sum= _html.escape(item.get("gemini_summary") or item.get("summary") or "설명 없음")

    search_src = item.get("search_source", "")
    src_hint   = {"topic": "topic 검색", "awesome": "awesome-list", "keyword": "키워드 검색"}.get(search_src, "")
    src_hint_html = f'<span style="font-size:10px;color:#9ca3af;margin-left:6px">{src_hint}</span>' if src_hint else ""

    topics_html = "".join(
        f'<span style="font-size:10px;padding:1px 7px;border-radius:10px;background:#dcfce7;color:#166534;margin-right:3px">{_html.escape(t)}</span>'
        for t in item.get("topics", [])[:6]
    )
    pct      = min(100, relevance)
    bar_html = (f'<div style="height:3px;background:#f3f4f6;border-radius:2px;margin-top:8px">'
                f'<div style="width:{pct}%;height:3px;background:{rel_color};border-radius:2px"></div></div>') if relevance else ""

    url    = _html.escape(item.get("url", ""), quote=True)
    repo   = _html.escape(item.get("repo", ""))
    stars  = item.get("stars", 0)
    lang   = _html.escape(item.get("lang", ""))
    forks  = item.get("forks", 0)
    pushed = _html.escape(item.get("pushed", item.get("updated", "")))

    card_html = f"""
<div style="border:1px solid {border_color};border-radius:12px;padding:1rem 1.2rem;
            margin-bottom:0.7rem;background:{bg_color};font-family:sans-serif">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:5px">
    <div>
      <span style="display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;
                   background:{src_bg};color:{src_fg};font-weight:500">{src_label}</span>
      {src_hint_html}&nbsp;
      <a href="{url}" target="_blank"
         style="font-size:14px;font-weight:500;color:#111827;text-decoration:none">
        {repo} ↗
      </a>
      {reason_html}
    </div>
    <div style="text-align:right">
      {rel_html}
      <div style="font-size:11px;color:#9ca3af">★ {stars} &middot; {lang}</div>
      <div style="font-size:10px;color:#9ca3af">🍴 {forks}</div>
    </div>
  </div>
  <div style="font-size:13px;color:#374151;line-height:1.5;margin-bottom:8px">{display_sum}</div>
  <div style="font-size:11px;color:#9ca3af;margin-bottom:5px">최근 커밋: {pushed}</div>
  {topics_html}
  {bar_html}
</div>"""

    st.components.v1.html(card_html, height=_card_height(relevance, reason, topics_html, bar_html, display_sum), scrolling=False)


def _card_height(relevance: int, reason: str, topics_html: str, bar_html: str,
                 summary: str = "") -> int:
    """카드 내용에 따라 동적으로 높이 계산"""
    h = 155                          # 기본값 130 → 155 (여백 확보)
    if reason:       h += 26         # 이유 한줄
    if topics_html:  h += 32         # 토픽 태그 줄
    if bar_html:     h += 16         # 적합도 바
    # summary 길이에 따라 추가 높이 (약 40자당 1줄 = 22px)
    if summary:
        extra_lines = max(0, len(summary) - 60) // 40
        h += extra_lines * 22
    return h


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


def render_hf_card(item: dict):
    import html as _html
    is_space  = item.get("type") == "space"
    bg_color  = "#fffaf0" if is_space else "#f0f7ff"
    border    = "#fcd34d" if is_space else "#93c5fd"
    type_label= "🚀 Space (데모)" if is_space else "🤗 Model"
    type_bg   = "#fef3c7" if is_space else "#dbeafe"
    type_fg   = "#92400e" if is_space else "#1e40af"

    hf_id    = _html.escape(item.get("id", ""))
    url      = _html.escape(item.get("url", ""), quote=True)
    likes    = item.get("likes_fmt", "0")
    modified = item.get("modified", "")
    summary  = _html.escape(item.get("summary", "") or "")
    sdk      = item.get("sdk", "")

    # 파이프라인 / 태스크
    pipeline_ko = item.get("pipeline_ko") or item.get("pipeline", "")
    pipeline_html = (
        f'<span style="font-size:10px;padding:1px 8px;border-radius:10px;'
        f'background:#e0e7ff;color:#3730a3;margin-left:4px">{_html.escape(pipeline_ko)}</span>'
    ) if pipeline_ko else ""

    # 라이브러리 태그 (모델만)
    lib_tags = item.get("lib_tags", [])
    lib_html = "".join(
        f'<span style="font-size:10px;padding:1px 7px;border-radius:10px;'
        f'background:#dcfce7;color:#166534;margin-right:3px">{_html.escape(t)}</span>'
        for t in lib_tags
    )

    # SDK 태그 (Space만)
    sdk_html = (
        f'<span style="font-size:10px;padding:1px 7px;border-radius:10px;'
        f'background:#f3e8ff;color:#6b21a8;margin-right:3px">{_html.escape(sdk)}</span>'
    ) if sdk else ""

    # downloads (모델만)
    dl = item.get("downloads_fmt", "")
    dl_html = f'<span style="font-size:11px;color:#6b7280">⬇ {dl}</span>' if dl else ""

    card_html = f"""
<div style="border:1px solid {border};border-radius:12px;padding:1rem 1.2rem;
            margin-bottom:0.7rem;background:{bg_color};font-family:sans-serif">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
    <div>
      <span style="display:inline-block;font-size:10px;padding:1px 7px;border-radius:10px;
                   background:{type_bg};color:{type_fg};font-weight:500">{type_label}</span>
      {pipeline_html}
      <a href="{url}" target="_blank"
         style="display:block;font-size:14px;font-weight:600;color:#111827;
                text-decoration:none;margin-top:4px">
        {hf_id} ↗
      </a>
    </div>
    <div style="text-align:right">
      <div style="font-size:13px;font-weight:600;color:#374151">❤️ {likes}</div>
      {dl_html}
      <div style="font-size:10px;color:#9ca3af;margin-top:2px">수정: {modified}</div>
    </div>
  </div>
  {'<div style="font-size:13px;color:#374151;line-height:1.5;margin-bottom:8px">' + summary + '</div>' if summary else ''}
  {lib_html}{sdk_html}
</div>"""
    st.components.v1.html(card_html, height=165 + (40 if summary else 0) + (20 if lib_tags or sdk else 0), scrolling=False)


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
    col_btn, col_gh, col_rd, col_q = st.columns([2, 1, 1, 2])
    with col_btn:
        do_search = st.button("🔍 검색", type="primary", use_container_width=True)
    with col_gh:
        use_github = st.checkbox("GitHub", value=True)
    with col_rd:
        use_reddit = st.checkbox("Reddit", value=True)
    with col_q:
        quality_mode = st.selectbox(
            "품질 기준",
            list(QUALITY_PRESETS.keys()),
            index=1,
            label_visibility="collapsed",
            help="★별점·커밋 날짜 기준으로 결과를 필터링합니다",
        )

    # 예시 버튼 클릭 시 자동 검색 트리거
    if st.session_state.trigger_search and query:
        do_search = True
        st.session_state.trigger_search = False

    # 쿼리 변경 시 캐시 초기화
    if query != st.session_state.last_query:
        st.session_state.search_results = {}
        st.session_state.last_query = query

    # ── 스마트 검색 실행 ────────────────────────────────────────────────────
    if do_search and query:
        # 1단계: 쿼리 확장 플랜 생성
        plan = build_plan(query, mode=quality_mode)

        # 전략 미리보기
        if plan.tech_terms:
            with st.expander("🧠 검색 전략 확인 (클릭)", expanded=False):
                st.caption(f"**원본 쿼리:** {plan.original}")
                st.caption(f"**기술 키워드:** {' · '.join(plan.tech_terms[:5])}")
                st.caption(f"**GitHub 쿼리 {len(plan.github_queries)}개:** "
                           + " | ".join(f"`{q}`" for q in plan.github_queries[:4]))
                st.caption(f"**Reddit 쿼리:** "
                           + " | ".join(f"`{q}`" for q in plan.reddit_queries[:3]))
                st.caption(f"**전략:** {plan.strategy_note}")
                st.caption(f"**품질 기준:** ★{plan.quality['min_stars']}+ · "
                           f"최근 {plan.quality['months']}개월 이내 커밋")

        with st.spinner("🔍 스마트 멀티쿼리 검색 중..."):
            db_scored = sorted(db, key=lambda a: semantic_score(a, query), reverse=True)

            # GitHub: 다중 쿼리로 검색 후 합치기
            gh_all: list[dict] = []
            if use_github:
                use_gem = bool(os.environ.get("GEMINI_API_KEY"))
                # 원본 쿼리
                gh_all += search_github(plan.original, max_results=8, use_gemini=use_gem)
                # 기술 키워드 쿼리 (최대 2개 추가)
                for tq in plan.github_queries[1:3]:
                    gh_all += search_github(tq, max_results=5, use_gemini=False)
                # 품질 필터 + 중복 제거 + 재정렬
                gh_all = deduplicate(gh_all)
                gh_all = quality_filter(gh_all, plan.quality)

            # Reddit: 다중 쿼리
            rd_all: list[dict] = []
            if use_reddit:
                for rq in plan.reddit_queries[:2]:
                    rd_all += search_reddit(rq, max_results=5)
                rd_all = deduplicate(rd_all)

            # HuggingFace: Models + Spaces
            hf_all = search_huggingface(
                plan.original,
                tech_terms=plan.tech_terms,
                max_models=8,
                max_spaces=5,
            )

        st.session_state.search_results = {
            "db": db_scored, "github": gh_all,
            "reddit": rd_all, "hf": hf_all,
            "query": query, "plan": plan,
        }

    # ── 결과 표시 ────────────────────────────────────────────────────────────
    cached = st.session_state.search_results
    if cached:
        db_scored  = cached.get("db", [])
        gh_results = cached.get("github", [])
        rd_results = cached.get("reddit", [])
        hf_results = cached.get("hf", [])
        q_label    = cached.get("query", query)
        plan       = cached.get("plan", None)

        gh_ok = [r for r in gh_results if "error" not in r]
        rd_ok = [r for r in rd_results if "error" not in r]
        hf_ok = [r for r in hf_results if "error" not in r]
        db_ok = [a for a in db_scored if semantic_score(a, q_label) > 0]

        # ── 탭 ───────────────────────────────────────────────────────────────
        tab_gh, tab_hf, tab_rd, tab_db = st.tabs([
            f"🐙 GitHub ({len(gh_ok)}개)",
            f"🤗 HuggingFace ({len(hf_ok)}개)",
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
                tech_hint = (f" · 기술 키워드: **{', '.join(plan.tech_terms[:3])}**"
                             if plan and plan.tech_terms else "")
                st.caption(
                    f"{'🤖 Gemini 쿼리 확장 · ' if has_gemini_key else ''}"
                    f"🧠 멀티쿼리 스마트 검색{tech_hint} — "
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

        # ── HuggingFace 탭 ───────────────────────────────────────────────────
        with tab_hf:
            if not hf_ok:
                st.warning("HuggingFace 검색 결과가 없습니다.")
            else:
                model_cnt = sum(1 for r in hf_ok if r.get("type") == "model")
                space_cnt = sum(1 for r in hf_ok if r.get("type") == "space")
                tech_hint = (f" · 기술 키워드: **{', '.join(plan.tech_terms[:2])}**"
                             if plan and plan.tech_terms else "")
                st.caption(
                    f"🤗 HuggingFace{tech_hint} — "
                    f"모델 **{model_cnt}개** · 데모 Space **{space_cnt}개** 발견"
                )
                for item in hf_ok:
                    render_hf_card(item)

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

        # ── 전체 결과 TXT 다운로드 ───────────────────────────────────────────
        st.divider()
        total = len(gh_ok) + len(rd_ok) + len(hf_ok) + len(db_ok)
        if total > 0:
            txt_content = _results_to_txt(q_label, gh_ok, rd_ok, db_ok, hf_ok)
            safe_q = "".join(c if c.isalnum() or c in "-_ " else "_" for c in q_label)[:30].strip()
            import datetime
            fname = f"search_{safe_q}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            st.download_button(
                label=f"📥 결과 전체 다운로드 ({total}개) — TXT",
                data=txt_content.encode("utf-8"),
                file_name=fname,
                mime="text/plain; charset=utf-8",
                use_container_width=True,
            )

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

            if model_used == "gemini-2.5-flash-lite":
                st.info("ℹ️ gemini-2.5-flash 할당량 초과 → lite 모델로 폴백")
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
