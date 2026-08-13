"""account-identity-actual check — 선언된 논리 계정의 자격 실체 검증 (global).

`project-gh-account-mapping` 은 `.envrc` GH_CONFIG_DIR ↔ ssh alias ↔ owner 라벨이
서로 같은 이름을 가리키는지만 본다 — 그 이름이 가리키는 gh 프로필 안의 토큰이
실제로 그 계정인지는 검증하지 않는다. 본 check 은 한 겹 더 나가, 이 머신의
account_manifest 바인딩이 선언한 `gh_config_dir` 프로필의 토큰을 `gh api user` 로
역조회해 선언된 `github_login` 과 실체를 대조한다(2026-08-12 사고 — `.envrc`·
`gh auth status`·`project show` 라벨이 셋 다 '16bitdo' 라고 답했으나 셋 다 틀렸다).

`project doctor` 의 `gh_identity_actual`(path-aware, cwd 하나만) 과 로직은
대응되지만 스코프가 다르다 — 여긴 cwd 와 무관하게 이 머신에 바인딩된 논리 계정
전체를 훑는다.

여기 등록하는 이유 — L4 anvyx 의 C6 pre-run gate 는 `anvyc project doctor` 가
아니라 이 **global** `anvyc doctor --strict --json` 을 호출하고, 반환된
`summary.critical` 카운트로 pass/fail 을 판정한다(anvyx `core/gate.py`
`run_doctor_gate`, 2026-08-12 실제 코드로 확인 — exit code 가 아니라 JSON summary
파싱 기반이라 `--strict` 의 exit code 경로와 무관하게도 동작한다). 이 check 하나를
global registry 에 등록하는 것만으로, anvyx 쪽 코드를 고치지 않고도 CRITICAL
불일치가 autopilot 실행을 막는 경로가 생긴다.

어떤 자격도 변경하지 않는다(read-only) — 불일치는 `suggestion` 으로 재인증 명령만
제시하고 대신 실행하지 않는다.
"""
from __future__ import annotations

import functools

from anvyc.checks.base import CheckContext, CheckResult, Severity
from anvyc.core import account_manifest, identity_cache, identity_probe
from anvyc.core.project_doctor import _gh_profile_hosts_files
from anvyc.core.project_info import expand_envrc_path


class AccountIdentityActualCheck:
    name = "account-identity-actual"

    def run(self, ctx: CheckContext) -> list[CheckResult]:  # noqa: ARG002
        bindings = account_manifest.load_bindings()
        if not bindings:
            return []  # 바인딩 미선언 머신 — 검증 대상 없음 (silent)

        results: list[CheckResult] = []
        for account_id, binding in sorted(bindings.items()):
            if not isinstance(binding, dict):
                continue
            expected = binding.get("github_login")
            gh_dir = binding.get("gh_config_dir")
            # 방어적 타입 체크 — account_manifest._expand() 와 동일 관용구.
            # YAML 이 문자열이 아닌 값(bool/int/list 등)을 담고 있어도 예외 없이 skip.
            if not isinstance(expected, str) or not expected:
                continue
            if not isinstance(gh_dir, str) or not gh_dir:
                continue  # 이 계정은 gh 라우팅 미선언 — 검증 대상 아님 (silent)

            # 바인딩 파일의 gh_config_dir 는 `~`/`$HOME`/`${HOME}` 어느 표기로도 올
            # 수 있다(테스트 fixture·문서 예시 모두 `~` 사용). Path(...).expanduser()
            # 는 `~` 만 확장하고 `$HOME` 리터럴은 그대로 두므로(Task 4 회귀 — probe 가
            # 항상 실패해 기능이 조용히 죽은 채 테스트만 통과했다) 반드시
            # expand_envrc_path() 로 확장한다 — `~`/`$HOME`/`${HOME}` 셋 다 처리한다.
            expanded_dir = expand_envrc_path(gh_dir)

            actual = identity_cache.probe_cached(
                # 키는 논리 계정 ID 가 아니라 **조회한 config 디렉터리**에서 파생한다.
                # project_doctor 의 gh_identity_actual 이 같은 프로필을 `.envrc` 라벨로
                # 키잉하고 있어, 값도 무효화 조건도 같은데 키가 갈려 같은 프로필을 두
                # 번 조회했다(리뷰 M2). 파생 규칙은 identity_cache 한 곳에 둔다.
                key=identity_cache.gh_probe_key(expanded_dir),
                # 이 프로필의 hosts.yml 하나가 아니라 형제 gh-* 프로필 전체의
                # hosts.yml 을 무효화 트리거로 쓴다. gh CLI 는 GH_CONFIG_DIR 로
                # 라벨(계정 표시)만 프로필별로 나누고 토큰은 OS 키체인에 저장해 모든
                # 프로필이 공유한다(2026-08-12 실측; upstream cli/cli#10136 — 다른
                # 프로필에서 재인증해도 이 프로필의 hosts.yml 은 그대로다). 이 무효화
                # 근거로 이미 검증된 project_doctor._gh_profile_hosts_files 를
                # 재사용한다 — 같은 로직을 중복 구현하면 한쪽만 고쳐지는 drift 위험.
                source=_gh_profile_hosts_files(expanded_dir),
                # functools.partial 로 expanded_dir 를 즉시 바인딩 — loop 안에서
                # `lambda: ...expanded_dir` 형태로 클로저를 쓰면 다음 iteration 에서
                # 재바인딩될 변수를 참조하는 걸로 오인되어 ruff B023 이 뜬다(이
                # 케이스는 probe_cached 가 probe() 를 같은 iteration 안에서 동기
                # 호출해 실제로는 안전하지만, partial 이 인자를 정의 시점에 바로
                # 값으로 굳혀 애초에 그 우려 자체를 없앤다 — mypy 타입 추론도 더 깔끔).
                probe=functools.partial(identity_probe.gh_login, expanded_dir),
            )
            if actual is None:
                # 조회 실패(gh 미설치·미인증·네트워크) — "모름"이지 "불일치"가
                # 아니다. global doctor 는 이 머신의 전 계정을 훑으므로, 모름까지
                # 보고하면 대부분 noise 가 된다 — 침묵한다.
                continue
            if actual == expected:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.INFO,
                        message=f"논리 계정 '{account_id}' gh 실체 일치: {actual}",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_name=self.name,
                        severity=Severity.CRITICAL,
                        message=(
                            f"논리 계정 '{account_id}' 의 gh 프로필 토큰이 실제로는 "
                            f"'{actual}' — 바인딩 선언은 '{expected}'"
                        ),
                        location=expanded_dir,
                        suggestion=(
                            # 확장된 절대경로를 쓴다(raw 값이 아니라) — raw 가 `~` 로
                            # 시작하면 큰따옴표 안에서 셸이 `~` 를 확장하지 않아
                            # (bash/zsh 공통 동작) 이 명령을 그대로 복붙하면 깨진다.
                            # `$HOME`/`${HOME}` 은 큰따옴표 안에서도 확장되지만
                            # `~` 는 안 되므로 세 표기를 통일해 절대경로로 낸다.
                            f'GH_CONFIG_DIR="{expanded_dir}" gh auth login -h github.com -p ssh '
                            "로 재인증 (자격 작업이므로 사용자가 직접 실행)"
                        ),
                    )
                )
        return results
