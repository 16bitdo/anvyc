<!--
PR 본문에 token / secret / 개인정보 (이메일, 내부 host, .env 본문 등) 가 포함되지 않도록 주의해 주세요.
포함된 경우 즉시 회전 + comment 로 알려주세요.
-->

## 요약

<!-- 1~3 줄. 무엇을 / 왜 (어떤 사용자 가치 / 문제 해결) -->

## 변경

<!-- 핵심 변경 항목 bullet. 큰 PR 은 file 그룹별 묶음. -->

-
-

## 관련 issue (해당 시)

<!-- Closes #N / Refs #N / Part of #N. issue 없는 자유 작업이면 비워 둠. -->

## 영향 범위

<!-- 새 명령 / 새 옵션 / 기본값 변경 / breaking change / 의존성 변경 등 — 사용자 측 영향 명시 -->

- breaking change: 예/아니오 (예인 경우 마이그레이션 가이드 본문 또는 RELEASE_NOTES.md 에 추가)
- dependency 추가/변경: 예/아니오 (예인 경우 packaging/homebrew/Formula/anvyc.rb 의 resource block 갱신 필요 — docs/homebrew-publishing.md)

## Test plan

- [ ] 단위 테스트 추가 / 갱신 (해당 시)
- [ ] `pytest` 통과
- [ ] `ruff check` + `mypy` 통과
- [ ] doc 변경 시 cross-link / anchor 깨짐 없음
- [ ] CI green
- [ ] (해당 시) 라이브 검증 — hermetic 외 시나리오 1회 실 실행 (`anvyc <command>` 실 결과 확인)

## 사전 확인

- [ ] 본 PR 본문 / commit 메시지 / 변경 파일에 token / secret / 개인정보 미포함
- [ ] anvyc 의 핵심 약속 (도구별 safe adapter / secret 기본 제외 / apply 전 dry-run / restore 전 local backup) 과 정합 (또는 의도된 일탈 시 본문에서 설명)
- [ ] [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md) §2 ~ §6 컨벤션 (branch / commit / style / test / git hygiene) 준수
