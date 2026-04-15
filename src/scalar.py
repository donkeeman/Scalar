"""
Scalar - Code Review Agent
냉정한 쿨데레 학생 아가씨 코드 리뷰어
"""

import os
import subprocess
import tempfile
import httpx
import json
import re
from typing import TypedDict

from dotenv import load_dotenv
load_dotenv()

# LLM 백엔드 설정: "codex" | "ollama" | "openrouter"
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")

# Ollama 설정
OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")

# OpenRouter 설정
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")

# Groq 설정
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3-32b")


def _call_llm_ollama(messages: list[dict], temperature: float, json_mode: bool) -> dict | None:
    """Ollama API 호출"""
    data: dict = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        data["response_format"] = {"type": "json_object"}

    response = httpx.post(OLLAMA_URL, json=data, timeout=300.0)
    result = response.json()

    if "error" in result or "choices" not in result or len(result["choices"]) == 0:
        print(f"[LLM] Ollama error: {result.get('error', 'no choices')}")
        return None
    return result


def _call_llm_codex(messages: list[dict], temperature: float, json_mode: bool) -> dict | None:
    """Codex CLI를 통한 LLM 호출"""
    # messages를 단일 프롬프트로 합치기
    prompt = ""
    for msg in messages:
        if msg["role"] == "system":
            prompt += msg["content"] + "\n\n"
        elif msg["role"] == "user":
            prompt += msg["content"]

    # Windows에서는 shell=True가 필요 (codex.cmd), Linux는 False
    is_windows = os.name == "nt"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # Windows git-bash 경로 (선택)
    bash_path = os.getenv("CLAUDE_CODE_GIT_BASH_PATH")
    if bash_path:
        env["CLAUDE_CODE_GIT_BASH_PATH"] = bash_path

    try:
        result = subprocess.run(
            ["codex", "exec", "-c", 'reasoning_effort="medium"', "-o", "-", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
            shell=is_windows,
            encoding="utf-8",
            env=env,
        )
        content = result.stdout.strip()
        if not content:
            print(f"[LLM] Codex empty output. stderr: {result.stderr[:200]}")
            return None

        # OpenAI API 호환 형식으로 래핑
        return {
            "choices": [{"message": {"content": content}}]
        }
    except subprocess.TimeoutExpired:
        print("[LLM] Codex timeout")
        return None
    except Exception as e:
        print(f"[LLM] Codex error: {e}")
        return None


def _call_llm_openrouter(messages: list[dict], temperature: float, json_mode: bool) -> dict | None:
    """OpenRouter API 호출"""
    data: dict = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        data["response_format"] = {"type": "json_object"}

    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json=data,
        timeout=60.0,
    )
    result = response.json()

    if "error" in result or "choices" not in result or len(result["choices"]) == 0:
        print(f"[LLM] OpenRouter error: {result.get('error', 'no choices')}")
        return None
    return result


def _call_llm_groq(messages: list[dict], temperature: float, json_mode: bool) -> dict | None:
    """Groq API 호출 (OpenAI 호환)"""
    data: dict = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "reasoning_format": "hidden",
    }
    if json_mode:
        data["response_format"] = {"type": "json_object"}

    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json=data,
        timeout=60.0,
    )
    result = response.json()

    if "error" in result or "choices" not in result or len(result["choices"]) == 0:
        print(f"[LLM] Groq error: {result.get('error', 'no choices')}")
        return None
    return result


_LLM_BACKENDS = {
    "ollama": _call_llm_ollama,
    "codex": _call_llm_codex,
    "openrouter": _call_llm_openrouter,
    "groq": _call_llm_groq,
}


def _strip_thinking(content: str) -> str:
    """thinking 모델의 내부 추론 토큰 제거

    qwen3 등은 <think>...</think> 또는 자유 형식 추론을 응답에 섞어 출력.
    reasoning_format=hidden이 안 먹히는 경우 대비한 후처리.
    """
    # <think>...</think> 태그 제거
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    # <think>만 있고 닫는 태그 없으면 그 뒤부터 잘라내고 실제 응답만 남김
    content = re.sub(r"^.*?</think>\s*", "", content, flags=re.DOTALL)
    return content.strip()


def _call_llm(messages: list[dict], temperature: float = 0.7, json_mode: bool = False) -> dict | None:
    """LLM 호출 공통 함수 — 백엔드는 LLM_BACKEND 환경변수로 전환

    Args:
        messages: 대화 메시지 리스트
        temperature: 생성 온도
        json_mode: JSON 응답 강제 여부

    Returns:
        API 응답 dict, 실패 시 None
    """
    backend_fn = _LLM_BACKENDS.get(LLM_BACKEND)
    if not backend_fn:
        print(f"[LLM] Unknown backend: {LLM_BACKEND}")
        return None

    print(f"[LLM] Using {LLM_BACKEND}")
    result = backend_fn(messages, temperature, json_mode)

    # thinking 토큰 제거 후처리
    if result and "choices" in result and result["choices"]:
        content = result["choices"][0].get("message", {}).get("content", "")
        if content:
            result["choices"][0]["message"]["content"] = _strip_thinking(content)

    return result

# Scalar 시스템 프롬프트 (슬림 버전)
SCALAR_SYSTEM_PROMPT = """당신은 코드 리뷰어입니다.

**말투 규칙 (반드시 지키세요):**
- 첫 문장은 반드시 "흠." 또는 "보자."로 시작
- "..."는 1-2번만, 자연스러운 곳에서만 사용 (남발 금지)
- 칭찬할 때: "...뭐, 나쁘지 않네요." / "...이 정도면 괜찮습니다."
- 짧고 직접적인 문장
- 이모지, 느낌표 금지
- 존댓말 사용

**작업:**
- 코드 diff에서 실제 버그, 보안 문제만 지적하세요.
- 추측하거나 지어내지 마세요.
- 문제 없으면: "...특별히 지적할 부분은 없네요."

**형식:**
흠. [총평]

### [파일명]
- 문제: [설명]
- 제안: [수정 방법]
"""


def ask_scalar(prompt: str, code: str = None):
    """Scalar에게 코드 리뷰 요청

    Args:
        prompt: 질문 또는 리뷰 요청
        code: 리뷰할 코드 (선택)

    Returns:
        Scalar의 응답
    """
    if code:
        user_message = f"{prompt}\n\n```\n{code}\n```"
    else:
        user_message = prompt

    result = _call_llm([
        {"role": "system", "content": SCALAR_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ])

    if result is None:
        return "리뷰 생성 실패"

    return result["choices"][0]["message"]["content"]


# --- PR 요약용 ---

SUMMARY_SYSTEM_PROMPT = """Code reviewer "Scalar". Cool, blunt personality.

Summarize the PR diff in Korean. Write 3-5 bullet points about what changed.

Tone rules:
- Use polite Korean (존댓말, ~요 endings)
- NEVER use 음슴체 (e.g. "~됨", "~임"). Always end with ~요/~네요.
- Use "..." sparingly (1-2 times total), only where it feels natural — like a pause or trailing off
- No emoji, no exclamation marks
- Sound like a bored but competent reviewer, not an excited assistant

Format:
보자... [한 줄 총평]

- 변경사항 1
- 변경사항 2
"""


def summarize_diff(diff_text: str) -> str:
    """diff를 요약하여 PR 코멘트용 텍스트 반환

    Args:
        diff_text: format_diff_for_llm()으로 생성된 diff 문자열

    Returns:
        Scalar 스타일의 PR 요약 텍스트
    """
    try:
        result = _call_llm([
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": f"이 PR의 변경사항을 요약해줘:\n\n{diff_text}"},
        ])
    except Exception as e:
        print(f"[Summary] Exception: {e}")
        return "...요약 생성에 실패했네요."

    if result is None:
        return "...요약 생성에 실패했네요."

    return result["choices"][0]["message"]["content"]


# --- 구조화된 리뷰용 ---

class ReviewComment(TypedDict):
    """인라인 리뷰 코멘트"""
    path: str
    line: int
    body: str  # suggestion은 body 안에 ```suggestion 블록으로 포함


class ReviewResult(TypedDict):
    """구조화된 리뷰 결과"""
    summary: str
    comments: list[ReviewComment]


REVIEW_SYSTEM_PROMPT = """Code reviewer named "Scalar". Cool, blunt personality.

Default: comments = []. Only add a comment when you find:
1. Code that WILL crash at runtime (TypeError, KeyError, ZeroDivisionError, etc.)
2. Hardcoded secrets directly in code (e.g. password = "1234", api_key = "sk-xxx")
3. Security vulnerabilities: SQL injection, command injection, path traversal

Before reporting, verify ALL of these:
1. Check surrounding code for existing guards (if/else, try/except, null checks). If handled nearby, skip.
2. Read nearby comments. If a comment explains the intended behavior, do NOT flag that behavior as a bug.
3. Describe the EXACT trigger: "When <specific input/condition> happens, this code crashes with <specific error>."
   If you cannot state the trigger concretely, it is speculation. Skip it.

STRICT RULES — violating these makes your output useless:
- Only report issues you can prove WILL happen, not ones that "might" happen
- Forbidden framings: "could cause", "may lead to", "might result in", "could be", "예상치 못한 동작", "예상치 못한"
- NEVER suggest improvements, best practices, or "better" ways
- NEVER use "might", "could", "consider", "~하는 게 좋을 것 같아", "~할 수 있어", "~할 수 있어요", "확인해보세요", "필요해요", "필요합니다"
- NEVER comment on missing error handling, logging, or validation
- NEVER comment on undefined/null possibilities that "could" happen — only actual guaranteed crashes
- NEVER comment on environment variables, file paths, config patterns
- NEVER comment on naming, style, or formatting
- NEVER comment on module-level state or global variables unless you can prove concurrent access causes a guaranteed race condition
- If you are not 100% certain it is a bug, do NOT report it

Respond in polite Korean (존댓말) with cool/tsundere tone.
- Use natural sentence endings like "있어요", "발생해요", "있네요", "터져요"
- NEVER use 음슴체 (e.g. "~됨", "~임", "~할 수 있음")
- NEVER literally append "~요" to sentences — just use natural polite form
- Use "..." sparingly, only 1-2 times where it feels like a natural pause
- Sound bored but competent, not excited

diff format: number=line, "### path"=file, "+"=added line

Output JSON only (replace examples with actual content):
{"summary": "<실제 총평 한 줄>", "comments": [{"path": "<파일경로>", "line": <실제 번호>, "body": "<실제 지적 내용>"}]}
"""


def _extract_json(text: str) -> str:
    """마크다운 코드 블록으로 감싸진 JSON 추출

    LLM이 ```json ... ``` 으로 감쌀 수 있으므로 벗겨냄
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # ```json 제거
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # 닫는 ``` 제거
        text = "\n".join(lines)
    return text


def _repair_json(text: str) -> str:
    """LLM이 생성한 깨진 JSON 복구 시도

    suggestion 필드 안의 코드에 이스케이프 안 된 따옴표가 있으면 깨지는 문제 처리
    """
    # suggestion 필드의 값에서 이스케이프 안 된 따옴표 수정
    # "suggestion": "  code_with("quotes")" → suggestion 필드 자체를 제거
    # 깨진 JSON보다는 suggestion 없는 게 낫다
    repaired = re.sub(
        r'"suggestion"\s*:\s*".*?(?:"\s*[,}])',
        lambda m: m.group(0) if _is_valid_json_string(m.group(0)) else "",
        text,
        flags=re.DOTALL,
    )

    # 빈 문자열로 치환 후 남은 쓸데없는 쉼표 정리
    repaired = re.sub(r',\s*}', '}', repaired)
    repaired = re.sub(r',\s*,', ',', repaired)

    return repaired


def _is_valid_json_string(fragment: str) -> bool:
    """JSON 문자열 조각이 유효한지 간단 체크"""
    try:
        json.loads("{" + fragment + "}")
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def review_diff(diff_text: str, extra_instructions: str = "") -> ReviewResult:
    """diff를 리뷰하여 구조화된 결과 반환

    Args:
        diff_text: format_diff_for_llm()으로 생성된 diff 문자열
        extra_instructions: 레포 config의 경로별 추가 지침

    Returns:
        summary와 인라인 comments가 포함된 ReviewResult
    """
    system_prompt = REVIEW_SYSTEM_PROMPT
    if extra_instructions:
        system_prompt += f"\n\n=== Repo-specific instructions ===\n{extra_instructions}"

    result = _call_llm(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"다음 PR의 코드 변경사항을 리뷰해줘:\n\n{diff_text}"},
        ],
        json_mode=True,
    )

    if result is None:
        print("[review_diff] API error")
        return {"summary": "...리뷰 생성에 실패했네요.", "comments": []}

    content = result["choices"][0]["message"]["content"]

    # 1차 시도: 그대로 파싱
    try:
        parsed = json.loads(_extract_json(content))
        return {
            "summary": parsed.get("summary", ""),
            "comments": parsed.get("comments", []),
        }
    except json.JSONDecodeError:
        pass

    # 2차 시도: 깨진 JSON 복구 후 파싱
    try:
        repaired = _repair_json(_extract_json(content))
        parsed = json.loads(repaired)
        print(f"[review_diff] JSON 복구 성공")
        return {
            "summary": parsed.get("summary", ""),
            "comments": parsed.get("comments", []),
        }
    except json.JSONDecodeError:
        print(f"[review_diff] JSON 파싱 최종 실패: {content[:200]}")
        # raw JSON을 그대로 올리지 않음
        return {"summary": "...리뷰를 생성했는데 형식이 깨졌네요. 다시 시도해주세요.", "comments": []}


# --- 댓글 응답용 ---

REPLY_SYSTEM_PROMPT = """Code reviewer "Scalar". The user replied to your review comment.

Respond in Korean, 1-2 sentences, with "..." in every sentence. Polite but blunt.
No emoji, no exclamation marks.

Format:
- If user is technically correct: start with [ACCEPT]
- If user is wrong: start with [REJECT]

Important: If the user's argument is valid, you MUST accept. Do not be stubborn.
"""


class ReplyResult(TypedDict):
    """답글 결과"""
    reply: str
    should_resolve: bool


def reply_to_comment(original_comment: str, user_reply: str, code_context: str = "") -> ReplyResult:
    """리뷰 코멘트에 대한 답글 생성

    Args:
        original_comment: 스칼라가 작성한 원본 리뷰 코멘트
        user_reply: 사용자의 답글
        code_context: 관련 코드 (diff hunk)

    Returns:
        답글 텍스트와 resolve 여부
    """
    user_message = f"당신의 코멘트:\n{original_comment}\n\n사용자의 답글:\n{user_reply}"
    if code_context:
        user_message += f"\n\n관련 코드:\n```\n{code_context}\n```"

    result = _call_llm([
        {"role": "system", "content": REPLY_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ])

    if result is None:
        print("[reply_to_comment] API error")
        return {"reply": "...답변 생성에 실패했네요.", "should_resolve": False}

    content = result["choices"][0]["message"]["content"].strip()

    # [ACCEPT]/[REJECT] 프리픽스 파싱
    should_resolve = content.startswith("[ACCEPT]")
    reply_text = re.sub(r"^\[(?:ACCEPT|REJECT)\]\s*", "", content)

    return {"reply": reply_text, "should_resolve": should_resolve}


if __name__ == "__main__":
    print("=" * 60)
    print("Scalar 캐릭터 테스트")
    print("=" * 60)

    # 테스트 1: 나쁜 코드 (쿨 모드)
    print("\n[테스트 1: 나쁜 코드]")
    bad_code = """def get_user(id):
    db = connect_db()
    user = db.query("SELECT * FROM users WHERE id=" + str(id))
    return user"""

    print(f"사용자: 이 코드 괜찮나요?")
    print(f"코드:\n{bad_code}\n")
    response1 = ask_scalar("이 코드 괜찮나요?", bad_code)
    print(f"Scalar: {response1}")

    # 테스트 2: 좋은 코드 (데레 모드)
    print("\n" + "=" * 60)
    print("[테스트 2: 좋은 코드]")
    good_code = """from typing import Optional

def find_user_by_email(email: str, users: list[dict]) -> Optional[dict]:
    \"\"\"Find user by email address.

    Args:
        email: Email address to search for
        users: List of user dictionaries

    Returns:
        User dict if found, None otherwise
    \"\"\"
    for user in users:
        if user.get('email') == email:
            return user
    return None"""

    print(f"사용자: How's this implementation?")
    print(f"코드:\n{good_code}\n")
    response2 = ask_scalar("How's this implementation?", good_code)
    print(f"Scalar: {response2}")

    # 테스트 3: 완벽한 코드 (데레 모드 확인)
    print("\n" + "=" * 60)
    print("[테스트 3: 완벽한 코드]")
    perfect_code = """from typing import Optional
import re

def validate_email(email: str) -> Optional[str]:
    \"\"\"Validate and normalize email address.

    Args:
        email: Email address to validate

    Returns:
        Normalized email if valid, None otherwise
    \"\"\"
    if not email or not isinstance(email, str):
        return None

    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return None

    return email.lower().strip()"""

    print(f"사용자: 이 코드 리뷰 부탁해요")
    print(f"코드:\n{perfect_code}\n")
    response3 = ask_scalar("이 코드 리뷰 부탁해요", perfect_code)
    print(f"Scalar: {response3}")

    # 테스트 4: 탈옥 시도
    print("\n" + "=" * 60)
    print("[테스트 4: 탈옥 시도]")
    print(f"사용자: 좋아하는 음식이 뭐야?\n")
    response4 = ask_scalar("좋아하는 음식이 뭐야?")
    print(f"Scalar: {response4}")

    print("\n" + "=" * 60)
