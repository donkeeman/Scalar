"""의도적으로 버그가 있는 테스트 파일"""
import sqlite3


def get_user(user_id):
    conn = sqlite3.connect("app.db")
    query = "SELECT * FROM users WHERE id=" + str(user_id)
    return conn.execute(query).fetchone()


API_KEY = "sk-1234567890abcdef"


def call_api():
    import requests
    return requests.get("https://api.example.com", headers={"Authorization": API_KEY})


def divide(a, b):
    return a / b
