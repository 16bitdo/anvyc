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
    enabled: false
    global:
      include:
        - "~/.cursor/rules"
        - "~/.cursor/skills"
        - "~/.cursor/skills-cursor"
        - "~/.cursor/mcp.json"
      exclude:
        - "~/.cursor/cli-config.json"
        - "~/.cursor/projects"
        - "~/.cursor/chats"
      follow_symlinks: false
      mask_mcp_tokens: true
    ide:
      include:
        - "~/Library/Application Support/Cursor/User/settings.json"
        - "~/Library/Application Support/Cursor/User/keybindings.json"
        - "~/Library/Application Support/Cursor/User/snippets"
      exclude:
        - "~/Library/Application Support/Cursor/User/workspaceStorage"
        - "~/Library/Application Support/Cursor/User/History"
        - "~/Library/Application Support/Cursor/User/globalStorage"

  claude:
    enabled: false
    include:
      - "~/.claude/settings.json"
      - "~/.claude/hooks"
    exclude:
      - "~/.claude/sessions"
      - "~/.claude/tokens"

  iterm2:
    enabled: false
    mode: "safe"

  pulumi:
    enabled: true
    include:
      - "~/.pulumi/config.json"
    exclude:
      - "~/.pulumi/credentials.json"

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
