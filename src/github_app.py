"""GitHub App Webhook 서버"""
import os
import re
import httpx
from typing import TypedDict, Literal
from fastapi import FastAPI, Request, HTTPException
from github import Github, GithubIntegration
from dotenv import load_dotenv
from src.scala import review_diff, reply_to_comment, ReviewResult

load_dotenv()

app = FastAPI()

# GitHub App 설정 (환경변수에서 로드)
APP_ID = os.getenv("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH")


def get_installation_token(installation_id: int) -> str:
    """GitHub App 설치 토큰 발급"""
    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    integration = GithubIntegration(APP_ID, private_key)
    return integration.get_access_token(installation_id).token


def get_github_client(installation_id: int) -> Github:
    """GitHub App 인증으로 클라이언트 생성"""
    return Github(get_installation_token(installation_id))


def resolve_review_thread(token: str, comment_node_id: str):
    """GraphQL API로 리뷰 스레드 resolve

    Args:
        token: GitHub App 설치 토큰
        comment_node_id: 코멘트의 GraphQL node ID
    """
    # 먼저 코멘트에서 스레드 ID를 가져옴
    query = """
    query($nodeId: ID!) {
      node(id: $nodeId) {
        ... on PullRequestReviewComment {
          pullRequestReviewThread { id }
        }
      }
    }
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 스레드 ID 조회
    resp = httpx.post(
        "https://api.github.com/graphql",
        headers=headers,
        json={"query": query, "variables": {"nodeId": comment_node_id}},
    )
    data = resp.json()
    thread_id = data.get("data", {}).get("node", {}).get("pullRequestReviewThread", {}).get("id")
    if not thread_id:
        print(f"[resolve] 스레드 ID를 찾을 수 없음: {data}")
        return

    # 스레드 resolve
    mutation = """
    mutation($threadId: ID!) {
      resolveReviewThread(input: {threadId: $threadId}) {
        thread { isResolved }
      }
    }
    """
    resp = httpx.post(
        "https://api.github.com/graphql",
        headers=headers,
        json={"query": mutation, "variables": {"threadId": thread_id}},
    )
    print(f"[resolve] Thread resolved: {resp.json()}")


class DiffLine(TypedDict):
    """파싱된 diff 라인 하나"""
    line_number: int | None  # new 파일 기준 라인 번호 (삭제된 줄은 None)
    content: str
    type: Literal["add", "delete", "context"]


class FileDiff(TypedDict):
    """파일 하나의 diff 정보"""
    path: str
    lines: list[DiffLine]


HUNK_PATTERN = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_patch(patch: str) -> list[DiffLine]:
    """diff 패치 문자열을 파싱하여 라인 정보 리스트로 변환

    Args:
        patch: GitHub API에서 받은 패치 문자열

    Returns:
        파싱된 DiffLine 리스트
    """
    result: list[DiffLine] = []
    new_line_num = 0

    for raw_line in patch.split("\n"):
        hunk_match = HUNK_PATTERN.match(raw_line)
        if hunk_match:
            new_line_num = int(hunk_match.group(1))
            continue

        if raw_line.startswith("+"):
            result.append({
                "line_number": new_line_num,
                "content": raw_line[1:],
                "type": "add",
            })
            new_line_num += 1
        elif raw_line.startswith("-"):
            result.append({
                "line_number": None,
                "content": raw_line[1:],
                "type": "delete",
            })
        elif raw_line.startswith(" "):
            result.append({
                "line_number": new_line_num,
                "content": raw_line[1:],
                "type": "context",
            })
            new_line_num += 1

    return result


def format_diff_for_llm(file_diffs: list[FileDiff]) -> str:
    """구조화된 diff 데이터를 LLM이 읽을 수 있는 문자열로 변환

    각 줄 앞에 라인 번호를 붙여서 LLM이 특정 줄을 참조할 수 있게 함

    Args:
        file_diffs: parse된 FileDiff 리스트

    Returns:
        라인 번호가 포함된 diff 문자열
    """
    output = ""
    for file_diff in file_diffs:
        output += f"\n### {file_diff['path']}\n"
        for line in file_diff["lines"]:
            prefix = {
                "add": "+",
                "delete": "-",
                "context": " ",
            }[line["type"]]
            line_num = f"{line['line_number']:>4}" if line["line_number"] is not None else "    "
            output += f"{line_num} {prefix} {line['content']}\n"

    return output


CODE_EXTENSIONS = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs'}
EXCLUDE_PATHS = {'examples/', 'tests/', 'test_', 'docs/', '__pycache__/'}
MAX_CHUNK_CHARS = 6000


def chunk_diff_lines(file_diff: FileDiff, max_chars: int = MAX_CHUNK_CHARS) -> list[FileDiff]:
    """파일 하나의 diff가 길면 줄 단위로 청크 분할

    Args:
        file_diff: 원본 FileDiff
        max_chars: 청크당 최대 글자수

    Returns:
        분할된 FileDiff 리스트 (짧으면 원본 그대로 1개)
    """
    full_text = format_diff_for_llm([file_diff])
    if len(full_text) <= max_chars:
        return [file_diff]

    chunks: list[FileDiff] = []
    current_lines: list[DiffLine] = []
    current_len = len(f"\n### {file_diff['path']}\n")  # 헤더 길이

    for line in file_diff["lines"]:
        # 줄 하나의 대략적 길이 추정
        line_len = len(f"{line['line_number'] or '':>4} + {line['content']}\n")

        if current_len + line_len > max_chars and current_lines:
            chunks.append({"path": file_diff["path"], "lines": current_lines})
            current_lines = []
            current_len = len(f"\n### {file_diff['path']}\n")

        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append({"path": file_diff["path"], "lines": current_lines})

    return chunks


def get_pr_diff(repo, pr_number: int) -> list[FileDiff]:
    """PR의 diff를 파싱하여 구조화된 데이터로 반환 (소스 코드만)

    examples/, tests/ 등 리뷰가 불필요한 경로는 자동 제외

    Args:
        repo: PyGithub Repository 객체
        pr_number: PR 번호

    Returns:
        파일별 diff 정보 리스트
    """
    pr = repo.get_pull(pr_number)
    files = pr.get_files()

    file_diffs: list[FileDiff] = []
    for file in files:
        # 제외 경로 필터링
        if any(file.filename.startswith(p) or f"/{p}" in file.filename for p in EXCLUDE_PATHS):
            continue

        ext = '.' + file.filename.split('.')[-1] if '.' in file.filename else ''
        if ext not in CODE_EXTENSIONS:
            continue

        if file.patch:
            file_diffs.append({
                "path": file.filename,
                "lines": parse_patch(file.patch),
            })

    return file_diffs


def post_review(repo, pr_number: int, review_result: ReviewResult, file_diffs: list[FileDiff]):
    """PR에 인라인 리뷰 코멘트 달기

    Args:
        repo: PyGithub Repository 객체
        pr_number: PR 번호
        review_result: LLM이 생성한 구조화된 리뷰
        file_diffs: diff 데이터 (코멘트 라인 번호 검증용)
    """
    pr = repo.get_pull(pr_number)

    # diff에 실제 존재하는 (path, line) 조합만 허용
    valid_lines: set[tuple[str, int]] = set()
    for fd in file_diffs:
        for line in fd["lines"]:
            if line["line_number"] is not None:
                valid_lines.add((fd["path"], line["line_number"]))

    # LLM이 잘못된 라인 번호를 줄 수 있으므로 필터링
    comments = []
    for c in review_result["comments"]:
        if (c["path"], c["line"]) not in valid_lines:
            print(f"[post_review] 유효하지 않은 코멘트 위치 무시: {c['path']}:{c['line']}")
            continue

        comments.append({
            "path": c["path"],
            "line": c["line"],
            "side": "RIGHT",
            "body": c["body"],
        })

    pr.create_review(
        body=review_result["summary"],
        event="COMMENT",
        comments=comments,
    )


BOT_LOGIN = "scala-agent[bot]"


@app.post("/webhook")
async def handle_webhook(request: Request):
    """GitHub Webhook 핸들러"""
    event_type = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()
    action = payload.get("action")

    # 리뷰 코멘트에 대한 답글 처리
    if event_type == "pull_request_review_comment" and action == "created":
        return await handle_comment_reply(payload)

    # PR 이벤트 처리
    if event_type == "pull_request" and action in ["opened", "synchronize", "reopened"]:
        return await handle_pr_review(payload)

    return {"status": "ignored", "reason": f"event '{event_type}' action '{action}' not handled"}


async def handle_pr_review(payload: dict):
    """PR 열림/업데이트 시 코드 리뷰"""
    pr_data = payload["pull_request"]
    pr_number = pr_data["number"]
    repo_full_name = payload["repository"]["full_name"]
    installation_id = payload["installation"]["id"]

    print(f"[Review] PR #{pr_number} on {repo_full_name}")

    try:
        gh = get_github_client(installation_id)
        repo = gh.get_repo(repo_full_name)

        file_diffs = get_pr_diff(repo, pr_number)
        print(f"[Review] Got {len(file_diffs)} files to review")

        # 파일별 → 청크별로 리뷰 요청 (LLM 컨텍스트 한계 대응)
        all_comments: list = []
        for fd in file_diffs:
            chunks = chunk_diff_lines(fd)
            for i, chunk in enumerate(chunks):
                diff_text = format_diff_for_llm([chunk])
                chunk_label = f" (chunk {i+1}/{len(chunks)})" if len(chunks) > 1 else ""
                print(f"[Review] Reviewing {fd['path']}{chunk_label} ({len(diff_text)} chars)")
                result = review_diff(diff_text)
                all_comments.extend(result["comments"])

        # 중복 코멘트 제거 (같은 파일에서 같은 body면 첫 번째만 유지)
        seen: set[str] = set()
        unique_comments: list = []
        for c in all_comments:
            key = f"{c['path']}:{c['body']}"
            if key not in seen:
                seen.add(key)
                unique_comments.append(c)
        if len(all_comments) != len(unique_comments):
            print(f"[Review] Deduplicated: {len(all_comments)} -> {len(unique_comments)} comments")
        all_comments = unique_comments

        if all_comments:
            summary = f"흠. {len(file_diffs)}개 파일을 봤는데... {len(all_comments)}건 지적할 게 있네요."
        else:
            summary = "...전체적으로 봤는데, 특별히 지적할 부분은 없네요."

        review_result: ReviewResult = {"summary": summary, "comments": all_comments}
        print(f"[Review] Generated review: {len(all_comments)} inline comments")

        post_review(repo, pr_number, review_result, file_diffs)
        print(f"[Review] Posted review")

        return {"status": "success", "pr": pr_number}

    except Exception as e:
        print(f"[Review] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_comment_reply(payload: dict):
    """리뷰 코멘트에 대한 답글 처리"""
    comment = payload["comment"]
    comment_author = comment["user"]["login"]

    # 자기 자신의 코멘트에는 응답하지 않음 (무한 루프 방지)
    if comment_author == BOT_LOGIN:
        return {"status": "ignored", "reason": "own comment"}

    # in_reply_to_id가 없으면 새 코멘트이므로 무시
    parent_comment_id = comment.get("in_reply_to_id")
    if not parent_comment_id:
        return {"status": "ignored", "reason": "not a reply"}

    pr_number = payload["pull_request"]["number"]
    repo_full_name = payload["repository"]["full_name"]
    installation_id = payload["installation"]["id"]

    print(f"[Reply] Comment on PR #{pr_number} by {comment_author}")

    try:
        gh = get_github_client(installation_id)
        repo = gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)

        # 원본 코멘트(우리 봇의 코멘트) 가져오기
        parent_comment = pr.get_review_comment(parent_comment_id)

        # 우리 봇의 코멘트에 대한 답글만 처리
        if parent_comment.user.login != BOT_LOGIN:
            return {"status": "ignored", "reason": "not a reply to bot"}

        # 답글 생성
        result = reply_to_comment(
            original_comment=parent_comment.body,
            user_reply=comment["body"],
            code_context=comment.get("diff_hunk", ""),
        )
        print(f"[Reply] Generated reply (resolve={result['should_resolve']}): {result['reply'][:100]}")

        # 답글 달기
        pr.create_review_comment_reply(parent_comment_id, result["reply"])
        print(f"[Reply] Posted reply")

        # 스칼라가 인정했으면 스레드 자동 resolve
        if result["should_resolve"]:
            token = get_installation_token(installation_id)
            resolve_review_thread(token, comment["node_id"])
            print(f"[Reply] Thread resolved")

        return {"status": "success", "reply_to": parent_comment_id}

    except Exception as e:
        print(f"[Reply] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Health check"""
    return {"status": "ok", "message": "Scala Code Review Bot"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
