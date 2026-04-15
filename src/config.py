"""레포별 .scalar.yml 설정 로더"""
from typing import TypedDict
import yaml


CONFIG_FILE = ".scalar.yml"


class PathInstruction(TypedDict):
    path: str
    instructions: str


class ScalarConfig(TypedDict):
    language: str
    drafts: bool
    ignore_title_keywords: list[str]
    path_filters: list[str]
    path_instructions: list[PathInstruction]


DEFAULT_CONFIG: ScalarConfig = {
    "language": "ko",
    "drafts": False,
    "ignore_title_keywords": [],
    "path_filters": [],
    "path_instructions": [],
}


def load_config(repo, ref: str = "HEAD") -> ScalarConfig:
    """레포 루트의 .scalar.yml 읽어서 설정 반환

    Args:
        repo: PyGithub Repository 객체
        ref: git ref (기본 HEAD = 기본 브랜치)

    Returns:
        기본값과 병합된 설정
    """
    try:
        content_file = repo.get_contents(CONFIG_FILE, ref=ref)
        raw = content_file.decoded_content.decode("utf-8")
        parsed = yaml.safe_load(raw) or {}
    except Exception:
        return DEFAULT_CONFIG.copy()

    review = parsed.get("review", {})
    return {
        "language": parsed.get("language", DEFAULT_CONFIG["language"]),
        "drafts": review.get("drafts", DEFAULT_CONFIG["drafts"]),
        "ignore_title_keywords": review.get("ignore_title_keywords", []),
        "path_filters": review.get("path_filters", []),
        "path_instructions": review.get("path_instructions", []),
    }


def should_skip_by_title(title: str, keywords: list[str]) -> bool:
    """PR 제목에 스킵 키워드가 포함되어 있는지 검사"""
    if not keywords:
        return False
    title_lower = title.lower()
    return any(kw.lower() in title_lower for kw in keywords)


def matches_path_filter(filepath: str, filters: list[str]) -> bool:
    """path_filters 패턴 매칭. `!` prefix면 제외 의미.

    리턴: True면 리뷰 대상, False면 제외.
    기본 동작: 필터가 비어있거나 제외 패턴만 있으면 모두 포함.
    """
    import fnmatch

    if not filters:
        return True

    excludes = [p[1:] for p in filters if p.startswith("!")]
    includes = [p for p in filters if not p.startswith("!")]

    # 제외 패턴 먼저 체크
    for pattern in excludes:
        if fnmatch.fnmatch(filepath, pattern):
            return False

    # include 패턴이 있으면 하나 이상 매치해야 함
    if includes:
        return any(fnmatch.fnmatch(filepath, p) for p in includes)

    return True


def get_path_instructions(filepath: str, instructions: list[PathInstruction]) -> list[str]:
    """파일 경로에 매칭되는 지침 문자열들 반환"""
    import fnmatch

    matched = []
    for inst in instructions:
        pattern = inst.get("path", "")
        if pattern and fnmatch.fnmatch(filepath, pattern):
            matched.append(inst.get("instructions", ""))
    return [m for m in matched if m]
