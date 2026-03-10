"""리뷰 테스트용 파일 — 버그 + 정상 코드 혼합"""
import os
import sqlite3


# --- 버그 있는 코드 (잡아야 함) ---

DB_PASSWORD = "super_secret_123"


def get_user(user_id):
    conn = sqlite3.connect("app.db")
    query = "SELECT * FROM users WHERE id=" + user_id
    return conn.execute(query).fetchone()


# --- 정상 코드 (false positive 나오면 안 됨) ---

API_URL = os.getenv("API_URL", "http://localhost:3000")
TIMEOUT = 30


def add(a: int, b: int) -> int:
    return a + b


def greet(name: str) -> str:
    return f"Hello, {name}"
