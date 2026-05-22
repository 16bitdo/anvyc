"""anvyc init 등에서 쓰는 정적 템플릿.

examples/anvyc.yaml 과 동일한 schema 의 축소판. 패키징되어 런타임에서 직접 참조 가능.
"""
from __future__ import annotations

DEFAULT_ANVYC_YAML = """\
version: 1

storage:
  root: ".anvyc"
  keep_backups: 5
  keep_local_backups: 5

security:
  secret_scan: true
  block_on_secret: true
  allow_encrypted_secrets: true

tools:
  shell:
    enabled: true
    files:
      - "~/.zshrc"
      - "~/.zprofile"

  git:
    enabled: true
    files:
      - "~/.gitconfig"
      - "~/.gitignore_global"

  aws:
    enabled: true
    include:
      - "~/.aws/config"
    exclude:
      - "~/.aws/credentials"

  gh:
    enabled: true
    include:
      - "~/.config/gh/config.yml"
    exclude:
      - "~/.config/gh/hosts.yml"

  cursor:
    enabled: true
    # Layer A — ~/.cursor/ (rules/skills/mcp/plugins/plans). 비워두면 adapter defaults 사용.
    global:
      include: []
      exclude: []
      follow_symlinks: false   # symlink 는 metadata 만 기록 (DESIGN.md §15.1)
      mask_mcp_tokens: false   # v0.2 까지는 scanner 차단만 사용
    # Layer B — Library/.../User (settings/keybindings/snippets/profiles).
    ide:
      include: []
      exclude: []
      global_storage_allowlist: []   # 예: ["anysphere.cursor-mcp"]
    # Layer C — project-local (opt-in). roots 가 비어 있으면 비활성.
    projects:
      enabled: false
      roots: []
      patterns: []   # 비우면 default: .cursor/rules, .cursor/skills, .cursor/mcp.json, .cursorrules

  claude:
    enabled: true
    # 비워두면 adapter 의 DEFAULT_INCLUDES / DEFAULT_EXCLUDES 가 적용된다.
    # 직접 지정 시 adapter defaults 위에 추가되며, 절대/`~` 경로 형식도 허용.
    include: []
    exclude: []

  iterm2:
    enabled: true
    mode: "safe"     # 전체 plist 동기화 금지, DESIGN.md §14.2 safe subset만

  pulumi:
    enabled: true
    include:
      - "~/.pulumi/config.json"
    exclude:
      - "~/.pulumi/credentials.json"

  # dev_env adapter (v0.7.0+) — direnv/asdf/pyenv/nvm 등 프로젝트별 환경 파일 추적.
  # default 로 enabled=false (사용자가 명시 enable 해야 안전 시작).
  dev_env:
    enabled: false
    project_roots:
      - "~/dev"
    patterns:
      - ".envrc"
      - ".tool-versions"
      - ".python-version"
      - ".nvmrc"
    exclude:
      - "**/node_modules/**"
      - "**/.venv/**"
      - "**/venv/**"
      - "**/.git/**"
      - "**/__pycache__/**"

  # shell_prompt adapter (v0.13.0+) — starship / powerlevel10k prompt 설정 파일.
  shell_prompt:
    enabled: true
    include:
      - "~/.config/starship.toml"
      - "~/.p10k.zsh"

doctor:
  cross_user:
    enabled: true
    known_user_aliases: {}
    scan_targets:
      - "~/.cursor/projects"
      - "~/.zshrc"
      - "~/.zprofile"
      - "~/.gitconfig"
      - "~/.ssh/config"
      - "~/.ssh/config.d"
      - "~/Library/Application Support/Cursor/User/settings.json"
      - "~/Library/Application Support/Cursor/User/keybindings.json"
      - "~/.claude/settings.json"
      - "~/.claude/CLAUDE.md"
    severity_overrides: {}
"""
