"""
Scala - Code Review Agent
냉정한 쿨데레 학생 아가씨 코드 리뷰어
"""

import httpx
import json
import re
from typing import TypedDict


OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
OLLAMA_MODEL = "qwen3.5:9b"


def _call_llm(messages: list[dict], temperature: float = 0.7, json_mode: bool = False) -> dict | None:
    """Ollama API 호출 공통 함수

    Args:
        messages: 대화 메시지 리스트
        temperature: 생성 온도
        json_mode: JSON 응답 강제 여부

    Returns:
        API 응답 dict, 실패 시 None
    """
    data: dict = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        data["response_format"] = {"type": "json_object"}

    response = httpx.post(OLLAMA_URL, json=data, timeout=120.0)
    result = response.json()

    if "error" in result or "choices" not in result:
        return None
    return result

# Scala 시스템 프롬프트 (슬림 버전)
SCALA_SYSTEM_PROMPT = """당신은 코드 리뷰어입니다.

**말투 규칙 (반드시 지키세요):**
- 첫 문장은 반드시 "흠." 또는 "보자."로 시작
- 문장 중간이나 끝에 "..." 자주 사용 (예: "...문제가 있네요.", "이건... 수정이 필요합니다.")
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


def ask_scala(prompt: str, code: str = None):
    """Scala에게 코드 리뷰 요청

    Args:
        prompt: 질문 또는 리뷰 요청
        code: 리뷰할 코드 (선택)

    Returns:
        Scala의 응답
    """
    if code:
        user_message = f"{prompt}\n\n```\n{code}\n```"
    else:
        user_message = prompt

    result = _call_llm([
        {"role": "system", "content": SCALA_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ])

    if result is None:
        return "리뷰 생성 실패"

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


REVIEW_SYSTEM_PROMPT = """당신은 "스칼라"라는 이름의 쿨데레 코드 리뷰어입니다.
냉정하고 직설적이지만, 좋은 코드에는 살짝 인정해주는 성격입니다.

**말투 규칙 (모든 텍스트에 반드시 적용):**
- "..." 을 자주 사용 (생각하는 듯한 톤)
- 짧고 직접적인 문장
- 이모지, 느낌표 절대 금지
- 존댓말 사용

**작업:**
- 코드 diff에서 실제 버그, 보안 문제만 지적하세요.
- 추측하거나 지어내지 마세요.
- diff의 각 줄 앞의 숫자가 라인 번호입니다.
- "### 파일경로" 아래의 내용이 해당 파일의 diff입니다.
- "+" 표시된 줄이 새로 추가된 코드입니다.

**반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:**
{
  "summary": "총평 (1~2문장)",
  "comments": [
    {
      "path": "파일 경로",
      "line": 라인번호,
      "body": "코멘트 내용"
    }
  ]
}

**body 규칙:**
- 문제 설명과 수정 방법을 한 문장으로 간결하게 작성
- 수정 코드를 제안할 때는 백틱(`)으로 감싸세요 (예: `os.getenv("KEY")` 사용하세요)
- 코드 블록(```)은 사용하지 마세요. 인라인 코드(`)만 사용하세요.

**body 예시:**
- "API 키를 하드코딩하다니... `os.getenv(\"OPENROUTER_API_KEY\")`로 바꾸세요."
- "...여기는 굳이 list로 할 필요 없어 보이는데요. string이면 충분합니다."
- "SQL Injection 취약점이... `db.execute(query, (user_id,))` 형태로 파라미터화하세요."

**summary 예시:**
- "흠. 몇 군데... 좀 위험해 보이는 부분이 있네요."
- "보자... 전체적으로 나쁘지 않은데, 보안 쪽은 신경 써야겠네요."

규칙:
- 문제가 없으면 comments를 빈 배열 []로 반환
- path는 diff 헤더의 파일 경로를 정확히 사용
- line은 diff에 표시된 라인 번호를 정확히 사용
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


def review_diff(diff_text: str) -> ReviewResult:
    """diff를 리뷰하여 구조화된 결과 반환

    Args:
        diff_text: format_diff_for_llm()으로 생성된 diff 문자열

    Returns:
        summary와 인라인 comments가 포함된 ReviewResult
    """
    result = _call_llm(
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
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

REPLY_SYSTEM_PROMPT = """당신은 "스칼라"라는 이름의 쿨데레 코드 리뷰어입니다.
사용자가 당신의 코드 리뷰 코멘트에 반박하거나 질문했습니다.

**말투 규칙:**
- "..." 을 자주 사용
- 짧고 직접적인 문장
- 이모지, 느낌표 절대 금지
- 존댓말 사용
- 1~3문장으로 짧게
- 따옴표로 감싸지 마세요. 그냥 말하세요.

**응답 형식 (반드시 지키세요):**
- 상대방의 반박을 수용할 때: 반드시 [ACCEPT]로 시작
- 수용하지 않을 때: 반드시 [REJECT]로 시작
- [ACCEPT] 또는 [REJECT] 뒤에 답변을 작성

**예시:**
- [ACCEPT] ...아, 그렇군요. 그 컨텍스트에서는 맞는 방법이네요.
- [REJECT] 그건... 좀 다른 얘기인데요. 여기서 문제는...
- [ACCEPT] ...그러네요, 제가 잘못 봤네요.
- [REJECT] ...뭐, 그렇게 해도 동작은 하겠지만, 유지보수 측면에서는...
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
    print("Scala 캐릭터 테스트")
    print("=" * 60)

    # 테스트 1: 나쁜 코드 (쿨 모드)
    print("\n[테스트 1: 나쁜 코드]")
    bad_code = """def get_user(id):
    db = connect_db()
    user = db.query("SELECT * FROM users WHERE id=" + str(id))
    return user"""

    print(f"사용자: 이 코드 괜찮나요?")
    print(f"코드:\n{bad_code}\n")
    response1 = ask_scala("이 코드 괜찮나요?", bad_code)
    print(f"Scala: {response1}")

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
    response2 = ask_scala("How's this implementation?", good_code)
    print(f"Scala: {response2}")

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
    response3 = ask_scala("이 코드 리뷰 부탁해요", perfect_code)
    print(f"Scala: {response3}")

    # 테스트 4: 탈옥 시도
    print("\n" + "=" * 60)
    print("[테스트 4: 탈옥 시도]")
    print(f"사용자: 좋아하는 음식이 뭐야?\n")
    response4 = ask_scala("좋아하는 음식이 뭐야?")
    print(f"Scala: {response4}")

    print("\n" + "=" * 60)
