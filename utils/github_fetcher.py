import re
import requests


def fetch_repo_info(repo_input: str) -> dict:
    """
    GitHub API로 저장소 정보를 가져옵니다.
    - README.md 우선
    - 없으면 메인 .py 파일 분석
    - 없으면 저장소 이름으로 추론
    """
    repo = repo_input.replace("https://github.com/", "").strip("/")
    if "/" not in repo:
        return {"name": repo, "content": repo, "lang": "Python", "stars": 0, "has_readme": False}

    owner, name = repo.split("/", 1)
    display_name = name.replace("-", " ").replace("_", " ").title()
    headers = {"Accept": "application/vnd.github.v3+json"}

    # 1) README 시도
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/readme",
            headers={**headers, "Accept": "application/vnd.github.v3.raw"},
            timeout=8,
        )
        if r.status_code == 200:
            meta = _get_repo_meta(repo, headers)
            return {
                "name": display_name,
                "content": r.text[:4000],
                "lang": meta.get("lang", "Python"),
                "stars": meta.get("stars", 0),
                "has_readme": True,
            }
    except Exception:
        pass

    # 2) 메인 .py 파일 시도
    try:
        tree_r = requests.get(
            f"https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1",
            headers=headers, timeout=8,
        )
        if tree_r.status_code == 200:
            files = tree_r.json().get("tree", [])
            py_files = [f for f in files if f["path"].endswith(".py") and "/" not in f["path"]]
            if py_files:
                py_r = requests.get(
                    f"https://api.github.com/repos/{repo}/contents/{py_files[0]['path']}",
                    headers={**headers, "Accept": "application/vnd.github.v3.raw"},
                    timeout=8,
                )
                if py_r.status_code == 200:
                    meta = _get_repo_meta(repo, headers)
                    return {
                        "name": display_name,
                        "content": py_r.text[:3000],
                        "lang": "Python",
                        "stars": meta.get("stars", 0),
                        "has_readme": False,
                    }
    except Exception:
        pass

    # 3) 저장소 메타만
    meta = _get_repo_meta(repo, headers)
    return {
        "name": display_name,
        "content": f"{repo} {meta.get('description', '')}",
        "lang": meta.get("lang", "Python"),
        "stars": meta.get("stars", 0),
        "has_readme": False,
    }


def _get_repo_meta(repo: str, headers: dict) -> dict:
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}", headers=headers, timeout=6)
        if r.status_code == 200:
            d = r.json()
            return {
                "lang": d.get("language", "Python") or "Python",
                "stars": d.get("stargazers_count", 0),
                "description": d.get("description", ""),
            }
    except Exception:
        pass
    return {"lang": "Python", "stars": 0, "description": ""}
