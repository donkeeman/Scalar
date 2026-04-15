"""RAG — 과거 리뷰 오탐 기억 및 유사 패턴 검색

ChromaDB를 사용해 과거 오탐(false positive) 코멘트를 저장하고,
새 리뷰 전에 현재 diff와 유사한 과거 오탐을 검색해 프롬프트에 주입.
"""
import os
from typing import Any, TypedDict
import chromadb
from chromadb.config import Settings


# ChromaDB 저장 경로 (서버에서는 /home/ubuntu/Scalar/.chroma 가 됨)
CHROMA_PATH = os.getenv("CHROMA_PATH", ".chroma")
COLLECTION_NAME = "scalar_rejections"


class RejectionEntry(TypedDict):
    """저장되는 오탐 항목"""
    comment_body: str
    code_context: str
    repo: str
    pr_number: int


_client: Any = None
_collection: Any = None


def _get_collection() -> Any:
    """ChromaDB 컬렉션을 lazy하게 초기화"""
    global _client, _collection
    if _collection is not None:
        return _collection

    _client = chromadb.PersistentClient(
        path=CHROMA_PATH,
        settings=Settings(anonymized_telemetry=False),
    )
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"description": "Scalar의 과거 오탐 리뷰 코멘트"},
    )
    return _collection


def store_rejection(
    comment_body: str,
    code_context: str,
    repo: str,
    pr_number: int,
    comment_id: str,
) -> None:
    """오탐 코멘트를 저장

    Args:
        comment_body: Scalar가 달았던 리뷰 코멘트 본문
        code_context: 그 코멘트가 달린 코드 (diff hunk)
        repo: 레포 full name (donkeeman/foo)
        pr_number: PR 번호
        comment_id: GitHub 코멘트 ID (중복 방지용 키)
    """
    collection = _get_collection()

    # 임베딩에 사용할 텍스트: 코멘트 + 코드 컨텍스트 조합
    document = f"코멘트: {comment_body}\n\n코드:\n{code_context}"

    collection.upsert(
        ids=[str(comment_id)],
        documents=[document],
        metadatas=[{
            "comment_body": comment_body,
            "code_context": code_context,
            "repo": repo,
            "pr_number": pr_number,
        }],
    )
    print(f"[RAG] Stored rejection: {repo}#{pr_number} {comment_id}")


def retrieve_similar(diff_text: str, n: int = 3) -> list[RejectionEntry]:
    """현재 diff와 유사한 과거 오탐 검색

    Args:
        diff_text: 리뷰 대상 diff 문자열
        n: 최대 반환 개수

    Returns:
        유사도 순 오탐 항목 리스트
    """
    collection = _get_collection()

    # 컬렉션이 비어있으면 스킵
    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[diff_text],
        n_results=min(n, collection.count()),
    )

    entries: list[RejectionEntry] = []
    metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
    for meta in metadatas:
        entries.append({
            "comment_body": meta.get("comment_body", ""),
            "code_context": meta.get("code_context", ""),
            "repo": meta.get("repo", ""),
            "pr_number": int(meta.get("pr_number", 0)),
        })
    return entries


def format_for_prompt(entries: list[RejectionEntry]) -> str:
    """검색된 오탐을 프롬프트에 삽입할 문자열로 포맷"""
    if not entries:
        return ""

    lines = ["Past false positives (avoid making similar comments):"]
    for i, entry in enumerate(entries, 1):
        lines.append(f"\n[{i}] Wrong comment: {entry['comment_body']}")
        code_preview = entry["code_context"][:300]
        lines.append(f"    Code: {code_preview}")
    return "\n".join(lines)
