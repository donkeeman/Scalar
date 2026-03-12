# Incremental Review Design

## 목표
PR synchronize 이벤트에서 변경된 파일만 리뷰하여 불필요한 LLM 호출 제거.

## 설계

### 분기 로직
- `opened` / `reopened` → 전체 파일 리뷰 (기존과 동일)
- `synchronize` → `before`/`after` SHA로 변경된 파일만 리뷰

### 구현 방식
1. `synchronize` payload에서 `before`, `after` SHA 추출
2. `repo.compare(before, after)`로 변경 파일 목록 조회
3. `get_pr_diff()`에 `changed_files` 필터 파라미터 추가
4. 이전 리뷰 코멘트는 그대로 유지 (GitHub이 outdated 자동 표시)

### 엣지 케이스
- `before`/`after` 없으면 전체 리뷰 폴백
- 변경 파일 0개 (코드 외 파일만 수정) → 리뷰 스킵

### 변경 파일
- `src/github_app.py`
