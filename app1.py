import time
import streamlit as st
from utils.db import load_db, save_db
from utils.classifier import infer_category, GEMINI_CALL_DELAY
from utils.matcher import semantic_score
from utils.github_fetcher import fetch_repo_info

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
.main .block-container { padding-top: 2rem; max-width: 900px; }
.app-card {
    border: 1px solid #e5e7eb; border-radius: 12px;
    padding: 1.1rem 1.3rem; margin-bottom: 0.75rem; background: white;
}
.app-card:hover { border-color: #9ca3af; }
.score-bar  { height: 4px; background: #f3f4f6; border-radius: 2px; margin-top: 8px; }
.score-fill { height: 4px; border-radius: 2px; background: #111827; }
.badge { display:inline-block;font-size:11px;padding:2px 9px;border-radius:20px;font-weight:500;margin-right:4px; }
.badge-eng  { background:#E6F1FB;color:#0C447C; }
.badge-rob  { background:#EEEDFE;color:#3C3489; }
.badge-ai   { background:#E1F5EE;color:#085041; }
.badge-mfg  { background:#FAECE7;color:#712B13; }
.badge-util { background:#FAEEDA;color:#633806; }
.cooldown-bar { height: 3px; background: #fde68a; border-radius: 2px; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

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


# ── 세션 상태 초기화 ─────────────────────────────────────────────────────────
if "last_api_call" not in st.session_state:
    st.session_state.last_api_call = 0.0   # 마지막 Gemini 호출 시각
if "analyze_result" not in st.session_state:
    st.session_state.analyze_result = None  # 분석 결과 캐시


# ── 유틸 ─────────────────────────────────────────────────────────────────────
def seconds_since_last_call() -> float:
    return time.time() - st.session_state.last_api_call

def cooldown_remaining() -> float:
    remaining = GEMINI_CALL_DELAY - seconds_since_last_call()
    return max(0.0, remaining)

def render_card(app: dict, score: int | None = None):
    bc = BADGE_MAP.get(app.get("cat_major", ""), "badge-util")
    tags_html = "".join(
        f'<span style="font-size:10px;padding:2px 7px;border-radius:12px;'
        f'background:#f3f4f6;color:#6b7280;margin-right:4px">{t}</span>'
        for t in app.get("tags", [])[:5]
    )
    if score is not None:
        pct = min(100, score * 4)
        score_html  = f'<div class="score-bar"><div class="score-fill" style="width:{pct}%"></div></div>'
        score_right = (f'<span style="font-size:18px;font-weight:500">{score}</span>'
                       f'<span style="font-size:11px;color:#9ca3af"> pts</span>')
    else:
        score_html  = ""
        score_right = f'<span style="font-size:12px;color:#9ca3af">★ {app.get("stars", 0)}</span>'

    repo = app.get("repo", "")
    repo_link = (
        f'<a href="https://github.com/{repo}" target="_blank" '
        f'style="font-size:12px;color:#6b7280;text-decoration:none">{repo} ↗</a>'
    ) if repo else ""

    st.markdown(f"""
    <div class="app-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
        <div>
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


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 App Matchmaker")
    st.caption("오픈소스 무료 앱을 찾고 등록하세요")
    st.markdown(f"[📂 GitHub 저장소]({GITHUB_URL})", unsafe_allow_html=False)
    st.divider()
    page = st.radio(
        "메뉴",
        ["🏠 홈", "➕ 저장소 등록", "🔎 앱 검색", "📂 카테고리 탐색", "📋 전체 목록"],
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

    # Gemini API 상태 표시
    st.divider()
    import os
    has_key = bool(os.environ.get("GEMINI_API_KEY"))
    if has_key:
        rem = cooldown_remaining()
        if rem > 0:
            st.caption(f"⏳ Gemini 쿨다운 {rem:.0f}초")
        else:
            st.caption("✅ Gemini API 준비됨")
    else:
        st.caption("⚠️ Gemini API 키 없음 (키워드 분류)")

db = load_db()

# ── 홈 ───────────────────────────────────────────────────────────────────────
if page == "🏠 홈":
    st.title("🔍 OpenSource App Matchmaker")
    st.markdown(
        "개발자는 **포트폴리오**를, 사용자는 **무료 앱**을 찾는 오픈소스 매칭 플랫폼입니다.  \n"
        f"[GitHub: {GITHUB_USER}/{GITHUB_REPO}]({GITHUB_URL})"
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("등록된 앱", len(db))
    c2.metric("카테고리", "4개 대분류")
    c3.metric("분류 엔진", "Gemini 2.0 Flash")
    st.divider()
    st.subheader("빠른 검색")
    quick = st.text_input("앱이 필요한 상황을 자연어로 입력하세요",
                          placeholder="예: 이족보행 로봇 균형 제어 파이썬")
    if quick:
        results = sorted(db, key=lambda a: semantic_score(a, quick), reverse=True)[:3]
        for app in results:
            render_card(app, score=semantic_score(app, quick))
    st.divider()
    st.subheader("최근 등록된 앱")
    for app in list(reversed(db))[:3]:
        render_card(app)

# ── 저장소 등록 ───────────────────────────────────────────────────────────────
elif page == "➕ 저장소 등록":
    st.title("➕ 저장소 / 앱 등록")
    tab1, tab2 = st.tabs(["GitHub 저장소 URL", "직접 입력"])

    with tab1:
        st.markdown("GitHub 저장소 URL 또는 `owner/repo` 형식으로 입력하세요.")
        repo_input = st.text_input(
            "저장소",
            placeholder=f"예: {GITHUB_USER}/{GITHUB_REPO}",
        )

        # ── 쿨다운 체크 & 버튼 ────────────────────────────────────────────
        rem = cooldown_remaining()
        btn_disabled = rem > 0

        if btn_disabled:
            st.info(f"⏳ Gemini 무료 티어 보호 — {rem:.0f}초 후 분석 가능합니다.")
            # 남은 시간 진행 바
            st.markdown(
                f'<div class="cooldown-bar"><div style="width:{((GEMINI_CALL_DELAY-rem)/GEMINI_CALL_DELAY)*100:.0f}%;'
                f'height:3px;background:#f59e0b;border-radius:2px"></div></div>',
                unsafe_allow_html=True,
            )

        col_btn, col_info = st.columns([2, 5])
        with col_btn:
            analyze_clicked = st.button(
                "🔍 분석 시작",
                type="primary",
                disabled=btn_disabled,
                help="Gemini 무료 티어: 연속 호출 방지를 위해 5초 간격을 둡니다.",
            )

        if analyze_clicked and repo_input and not btn_disabled:
            st.session_state.analyze_result = None  # 이전 결과 초기화

            with st.spinner("README / 코드 가져오는 중..."):
                info = fetch_repo_info(repo_input)

            with st.spinner(f"Gemini로 카테고리 분류 중... (최대 {GEMINI_CALL_DELAY+10}초)"):
                cat = infer_category(info["content"], repo_input)
                st.session_state.last_api_call = time.time()  # 호출 시각 기록

            st.session_state.analyze_result = {"info": info, "cat": cat, "repo": repo_input}

        # ── 결과 표시 ─────────────────────────────────────────────────────
        res = st.session_state.analyze_result
        if res:
            info, cat, repo_input_cached = res["info"], res["cat"], res["repo"]
            model_used = cat.get("_model_used", "keyword")

            st.success(f"분석 완료! (사용 모델: `{model_used}`)")

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
                st.progress(cat["confidence"] / 100, text=f"분류 신뢰도 {cat['confidence']}%")

            if model_used == "exhausted":
                st.warning("⚠️ Gemini 모든 모델 할당량 초과. 키워드 분류 결과입니다.")
            elif model_used == "gemini-2.0-flash-lite":
                st.info("ℹ️ gemini-2.0-flash 할당량 초과 → gemini-2.0-flash-lite로 폴백했습니다.")

            already = any(a["repo"] == repo_input_cached for a in db)
            if already:
                st.warning("이미 등록된 저장소입니다.")
            else:
                if st.button("✅ DB에 등록", type="primary"):
                    db.append({
                        "id": len(db) + 1,
                        "name": info["name"],
                        "repo": repo_input_cached,
                        "owner": repo_input_cached.split("/")[0],
                        "summary": cat["summary"],
                        "cat_major": cat["major"],
                        "cat_mid": cat["mid"],
                        "cat_minor": cat["minor"],
                        "lang": info.get("lang", "Python"),
                        "stars": info.get("stars", 0),
                        "tags": cat.get("tags", []),
                        "has_readme": info.get("has_readme", False),
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

# ── 앱 검색 ───────────────────────────────────────────────────────────────────
elif page == "🔎 앱 검색":
    st.title("🔎 앱 검색 & 매칭")
    query = st.text_input(
        "찾고 싶은 앱을 자연어로 설명하세요",
        placeholder="예: 이족보행 로봇 균형 제어 파이썬으로 된 것",
    )
    examples = ["MIM 수축률 예측", "이족보행 균형 제어", "OpenFOAM 유동 해석", "몰드 설계 최적화", "로봇 시뮬레이션"]
    cols = st.columns(len(examples))
    for i, eq in enumerate(examples):
        if cols[i].button(eq, key=f"eq{i}"):
            query = eq

    if query:
        scored = sorted(db, key=lambda a: semantic_score(a, query), reverse=True)
        matched = sum(1 for a in scored if semantic_score(a, query) > 0)
        st.caption(f"'{query}' — {matched}개 매칭")
        st.divider()
        for app in scored:
            render_card(app, score=semantic_score(app, query))
        st.divider()
        st.subheader("GitHub에서 더 찾기")
        for kw in query.split()[:3]:
            st.markdown(
                f"[🔗 '{kw}' GitHub 검색]"
                f"(https://github.com/search?q={kw}+streamlit&type=repositories)"
            )

# ── 카테고리 탐색 ─────────────────────────────────────────────────────────────
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
            st.info("아직 등록된 앱이 없습니다. '저장소 등록' 메뉴에서 추가해 보세요.")

# ── 전체 목록 ─────────────────────────────────────────────────────────────────
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
