"""RAG 메모리 관리 CLI

사용법:
    uv run python scripts/rag_admin.py stats
    uv run python scripts/rag_admin.py add --comment "..." --code "..."
    uv run python scripts/rag_admin.py list
    uv run python scripts/rag_admin.py search "<쿼리 텍스트>"
    uv run python scripts/rag_admin.py clear
"""
import argparse
import sys
import uuid

# scripts/ → 프로젝트 루트로 이동해서 src/ 임포트 가능하게
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag import _get_collection, store_rejection, retrieve_similar, format_for_prompt


def cmd_stats():
    col = _get_collection()
    print(f"Collection: {col.name}")
    print(f"Count: {col.count()}")


def cmd_add(args):
    comment_id = args.id or f"manual-{uuid.uuid4().hex[:8]}"
    store_rejection(
        comment_body=args.comment,
        code_context=args.code or "",
        repo=args.repo or "manual",
        pr_number=args.pr or 0,
        comment_id=comment_id,
    )
    print(f"Added: {comment_id}")


def cmd_list():
    col = _get_collection()
    if col.count() == 0:
        print("Empty")
        return
    result = col.get()
    for i, (doc_id, meta) in enumerate(zip(result["ids"], result["metadatas"]), 1):
        print(f"[{i}] {doc_id}")
        print(f"    repo: {meta.get('repo')}#{meta.get('pr_number')}")
        print(f"    comment: {meta.get('comment_body', '')[:100]}")
        print()


def cmd_search(query: str):
    results = retrieve_similar(query, n=5)
    if not results:
        print("No results")
        return
    print(format_for_prompt(results))


def cmd_clear():
    confirm = input("Really clear all entries? [y/N]: ")
    if confirm.lower() != "y":
        print("Aborted")
        return
    col = _get_collection()
    ids = col.get()["ids"]
    if ids:
        col.delete(ids=ids)
    print(f"Cleared {len(ids)} entries")


def main():
    parser = argparse.ArgumentParser(description="Scalar RAG memory admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats")
    sub.add_parser("list")

    add = sub.add_parser("add")
    add.add_argument("--comment", required=True, help="오탐 코멘트 본문")
    add.add_argument("--code", default="", help="코드 컨텍스트")
    add.add_argument("--repo", default="manual", help="레포 이름 (기본: manual)")
    add.add_argument("--pr", type=int, default=0, help="PR 번호")
    add.add_argument("--id", default=None, help="코멘트 ID (기본: 자동 생성)")

    search = sub.add_parser("search")
    search.add_argument("query", help="검색 쿼리 텍스트")

    sub.add_parser("clear")

    args = parser.parse_args()

    if args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "search":
        cmd_search(args.query)
    elif args.cmd == "clear":
        cmd_clear()


if __name__ == "__main__":
    main()
