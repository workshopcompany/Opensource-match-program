# 🔍 OpenSource App Matchmaker

개발자는 **포트폴리오 노출**을, 사용자는 **무료 앱**을 찾는 오픈소스 매칭 플랫폼입니다.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://your-app.streamlit.app)

## 주요 기능

| 기능 | 설명 |
|------|------|
| 저장소 자동 분석 | GitHub URL → README 읽기 → Gemini AI 카테고리 자동 분류 |
| 자연어 검색 | "이족보행 로봇 균형 제어" → 관련 앱 매칭 & 점수 |
| 카테고리 탐색 | Engineering › Manufacturing › MIM 3단계 드릴다운 |
| Gemini 폴백 | gemini-2.0-flash 할당량 초과 시 gemini-2.0-flash-lite 자동 전환 |
| Rate Limit 보호 | 무료 티어 보호를 위해 API 호출 간 5초 쿨다운 UI 내장 |

## 카테고리 구조

```
Engineering  ›  Manufacturing  ›  MIM / Powder Metallurgy
             ›  CFD/Simulation ›  OpenFOAM / FEA
             ›  Materials Science

Robotics     ›  Locomotion Control  ›  Bipedal Walking
             ›  Simulation          ›  PyBullet / MuJoCo / ROS
             ›  Perception          ›  SLAM / Object Detection

AI / ML      ›  NLP        ›  LLM Wrapper / RAG Pipeline
             ›  Automation  ›  LangChain / Workflow

Utility      ›  Data Tools  ›  Dashboard / Scraper
             ›  DevOps      ›  GitHub Actions / CI/CD
```

## Gemini 모델 전략

```
1순위: gemini-2.0-flash       (고성능, 무료 티어 15 RPM)
2순위: gemini-2.0-flash-lite  (경량, 429 할당량 초과 시 자동 폴백)
폴백:  키워드 기반 분류         (API 없을 때도 항상 동작)
```

## 로컬 실행

```bash
git clone https://github.com/workcompany/opensource-match-program
cd opensource-match-program
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud 배포

1. GitHub에 push: `https://github.com/workcompany/opensource-match-program`
2. [share.streamlit.io](https://share.streamlit.io) → New app → 저장소 선택
3. Secrets 설정:
   ```toml
   GEMINI_API_KEY = "AIzaSy-..."
   ```
4. Deploy!

## 기술 스택

- **Frontend/Backend:** Streamlit
- **분류 엔진:** 키워드 매칭 + Gemini 2.0 Flash (자동 폴백)
- **데이터:** JSON 파일 (추후 SQLite/Supabase 확장 가능)
- **GitHub 연동:** GitHub REST API (README / 파일 트리)
