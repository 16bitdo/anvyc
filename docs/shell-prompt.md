# shell prompt 통합 — `anvyc prompt`

`anvyc prompt` 는 현재 디렉터리의 **per-project 계정 라우팅**을 shell prompt 용
한 줄로 출력한다. `project show` 를 매번 실행하지 않고도 이 프로젝트가 어느
AWS / GitHub / Claude Code / Pulumi 계정으로 라우팅되는지 prompt 에 상시 표시할
수 있다.

## 출력 형식

설정된 필드만 공백 구분 `key:value` 로 출력하고, 아무것도 없으면 **빈 출력**이다.

```bash
$ cd ~/dev/my-personal-repo && anvyc prompt
aws:company-dev gh:16bitdo claude:edward

$ anvyc prompt --json
{"aws": "company-dev", "gh": "16bitdo", "claude": "edward"}
```

| key | 출처 |
|---|---|
| `aws` | `.envrc` 의 `AWS_PROFILE` |
| `gh` | `.envrc` 의 `GH_CONFIG_DIR` → gh 계정 |
| `claude` | `.envrc` 의 `CLAUDE_CONFIG_DIR` → Claude Code 계정 |
| `pulumi` | `Pulumi.yaml` 의 `backend.url` |

- prompt 컨텍스트라 **어떤 오류도 셸을 깨지 않는다** — 경로 부재·파싱 실패 시
  조용히 빈 출력 + exit 0.
- 호출당 ~70ms (starship `command_timeout` 기본 500ms 이내).

## starship 연동

`~/.config/starship.toml` 에 custom 모듈 추가:

```toml
[custom.anvyc]
description = "anvyc per-project 계정 라우팅"
command = "anvyc prompt"
when = true
format = "[$output]($style) "
style = "bold cyan"
shell = ["bash", "--noprofile", "--norc"]
```

그리고 `format` 의 원하는 위치에 `$custom` (또는 `${custom.anvyc}`) 을 배치한다.
빈 디렉터리에서는 `anvyc prompt` 가 빈 문자열을 내므로 세그먼트가 사실상
보이지 않는다. 완전히 숨기려면 `when` 에 출력 유무 검사를 둘 수 있다 (명령 2회
실행):

```toml
when = "test -n \"$(anvyc prompt)\""
```

## powerlevel10k 연동

`~/.p10k.zsh` 에 custom 세그먼트 함수 추가:

```zsh
function prompt_anvyc() {
  local out
  out="$(anvyc prompt 2>/dev/null)" || return
  [[ -n $out ]] && p10k segment -f cyan -t "$out"
}
```

그리고 `POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS` (또는 `LEFT`) 에 `anvyc` 를 추가한다:

```zsh
typeset -g POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=( ... anvyc )
```

`out` 이 비어 있으면 `p10k segment` 를 호출하지 않으므로 세그먼트가 숨겨진다.

## 참고

- `anvyc prompt` 는 read-only — 설정을 변경하지 않는다.
- 라우팅 계정을 machine-readable 하게 더 자세히 보려면 `anvyc project show --json`
  (README §11) 을 사용한다.
- starship/p10k **설정 파일 자체**의 백업·동기화는 anvyc 의 `shell_prompt`
  어댑터가 담당한다 (`~/.config/starship.toml` · `~/.p10k.zsh`).
