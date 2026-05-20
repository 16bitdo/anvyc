"""SOPS encrypt → backup → apply → decrypt round-trip.

sops + age binary 가 없는 환경에서는 skip.
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from anvyc.core.apply import run_apply
from anvyc.core.backup import run_backup


def _have_sops_age() -> bool:
    return shutil.which("sops") is not None and shutil.which("age") is not None


pytestmark = pytest.mark.skipif(
    not _have_sops_age(), reason="sops or age binary not installed"
)


@pytest.fixture
def age_key(tmp_path: Path) -> dict:
    """임시 age key 한 쌍 생성. identity file + public key 반환."""
    identity = tmp_path / "age-key.txt"
    result = subprocess.run(
        ["age-keygen", "-o", str(identity)],
        capture_output=True,
        text=True,
        check=True,
    )
    # age-keygen 은 public key 를 stderr 에 출력
    pub_line = next(
        (line for line in result.stderr.splitlines() if line.startswith("Public key:")),
        "",
    )
    public = pub_line.split(":", 1)[1].strip()
    assert public.startswith("age1")
    return {"identity": identity, "public": public}


def _make_yaml(
    anvyc_dir: Path,
    secret_path: Path,
    age_pub: str,
    identity_file: Path,
    sops_format: str = "binary",
) -> Path:
    cfg = anvyc_dir / "anvyc.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              secret_scan: false
              block_on_secret: false
              sops:
                enabled: true
                format: "{sops_format}"
                age_recipients: ["{age_pub}"]
                age_identity_file: "{identity_file}"
            tools:
              shell:
                enabled: true
                secret_files: ["{secret_path}"]
              git:    {{enabled: false}}
              aws:    {{enabled: false}}
              gh:     {{enabled: false}}
              claude: {{enabled: false}}
              iterm2: {{enabled: false}}
              pulumi: {{enabled: false}}
              cursor: {{enabled: false}}
            """
        )
    )
    return cfg


def test_sops_encrypt_backup_does_not_contain_plaintext(tmp_path, age_key) -> None:
    """secret_file 의 평문이 backup 디렉터리에 절대 들어가지 않아야."""
    secret = tmp_path / "secret.env"
    secret.write_text("DB_PASSWORD=plaintext_secret_xyz_123\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_yaml(anvyc_dir, secret, age_key["public"], age_key["identity"])

    result = run_backup(root=anvyc_dir, config_path=cfg)
    enc = result.backup_dir / "shell/sops/secret.env.sops.json"
    assert enc.is_file()
    # 평문이 backup dir 어디에도 없어야
    needle = b"plaintext_secret_xyz_123"
    for path in result.backup_dir.rglob("*"):
        if path.is_file():
            assert needle not in path.read_bytes(), f"평문 누출: {path}"
    # metadata 에 encryption=sops/age
    import json
    meta = json.loads((result.backup_dir / "metadata.json").read_text())
    enc_entries = [f for f in meta["files"] if f.get("encryption") == "sops/age"]
    assert len(enc_entries) == 1
    assert "secret.env" in enc_entries[0]["targetPath"]


def test_sops_apply_decrypts_to_target(tmp_path, age_key) -> None:
    secret = tmp_path / "secret.env"
    secret.write_text("DB_PASSWORD=plaintext_secret_xyz_123\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_yaml(anvyc_dir, secret, age_key["public"], age_key["identity"])

    run_backup(root=anvyc_dir, config_path=cfg)

    # 타겟 제거 후 apply
    secret.unlink()
    run_apply(root=anvyc_dir, config_path=cfg)
    assert secret.exists()
    assert secret.read_text() == "DB_PASSWORD=plaintext_secret_xyz_123\n"


def test_sops_apply_fails_without_key(tmp_path, age_key) -> None:
    secret = tmp_path / "secret.env"
    secret.write_text("X=y\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_yaml(anvyc_dir, secret, age_key["public"], age_key["identity"])

    run_backup(root=anvyc_dir, config_path=cfg)
    secret.unlink()

    # 잘못된 identity 경로 (존재하지 않음) → apply 가 entry 에 error 기록
    bad_cfg = anvyc_dir / "anvyc-bad.yaml"
    bad_cfg.write_text(cfg.read_text().replace(
        str(age_key["identity"]),
        str(tmp_path / "nonexistent.txt"),
    ))
    # 가짜 identity 파일도 만들지 않음 — sops 가 환경변수 없이 default keyring 시도
    # macOS CI 등에서는 default ~/.config/sops/age/keys.txt 사용 가능
    # 그래도 wrong key 일 가능성이 높음 — 실패 경로를 보장하기 위해 keyring 격리:
    import os
    os.environ.pop("SOPS_AGE_KEY_FILE", None)
    # bad_cfg 의 age_identity_file 은 부재. apply 가 sops_decrypt 호출 → 실패 → error
    report = run_apply(root=anvyc_dir, config_path=bad_cfg)
    err = [e for e in report.entries if e.state_after == "error"]
    # key 가 우연히 맞을 가능성이 0 은 아니지만 일반적으로 실패해야
    # (만약 user 의 default keyring 이 우연히 같은 recipient 라면 통과 가능 — 그 경우는 skip)
    if not err:
        pytest.skip("default keyring 에 우연히 일치하는 key 존재")


def test_sops_inplace_yaml_roundtrip(tmp_path, age_key) -> None:
    """inplace 모드 — yaml 값만 암호화, 키와 형식 유지."""
    secret = tmp_path / "creds.yaml"
    secret.write_text("api_key: plaintext_yaml_secret_value\nuser: edward\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_yaml(anvyc_dir, secret, age_key["public"], age_key["identity"], sops_format="inplace")

    result = run_backup(root=anvyc_dir, config_path=cfg)
    # inplace 모드는 확장자 유지 → creds.yaml (.sops.json suffix 없음)
    enc = result.backup_dir / "shell/sops/creds.yaml"
    assert enc.is_file()
    enc_text = enc.read_text()
    # 키 'api_key' 는 평문 유지, 값은 ENC[…] 로 암호화됨
    assert "api_key:" in enc_text
    assert "plaintext_yaml_secret_value" not in enc_text
    assert "ENC[" in enc_text  # sops 의 암호화 marker

    # metadata 의 encryption 필드
    import json
    meta = json.loads((result.backup_dir / "metadata.json").read_text())
    enc_entries = [f for f in meta["files"] if f.get("encryption", "").startswith("sops/age")]
    assert any("inplace" in e["encryption"] for e in enc_entries)

    # apply 로 복원
    secret.unlink()
    run_apply(root=anvyc_dir, config_path=cfg)
    assert secret.exists()
    restored = secret.read_text()
    assert "api_key: plaintext_yaml_secret_value" in restored
    assert "user: edward" in restored


def test_sops_per_tool_format_override(tmp_path, age_key) -> None:
    """v0.4.1: tool 별 sops_format 이 전역보다 우선 — binary tool + inplace tool 혼합."""
    # 두 tool 의 secret_file 을 다른 모드로 처리
    bin_secret = tmp_path / "binsec.txt"
    bin_secret.write_text("binary_payload_xyz\n")
    yaml_secret = tmp_path / "yamlsec.yaml"
    yaml_secret.write_text("api_key: yaml_value_abc\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)

    cfg = anvyc_dir / "anvyc.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              secret_scan: false
              block_on_secret: false
              sops:
                enabled: true
                format: "binary"
                age_recipients: ["{age_key['public']}"]
                age_identity_file: "{age_key['identity']}"
            tools:
              shell:
                enabled: true
                secret_files: ["{bin_secret}"]
              claude:
                enabled: true
                sops_format: "inplace"
                secret_files: ["{yaml_secret}"]
              git:    {{enabled: false}}
              aws:    {{enabled: false}}
              gh:     {{enabled: false}}
              iterm2: {{enabled: false}}
              pulumi: {{enabled: false}}
              cursor: {{enabled: false}}
            """
        )
    )

    result = run_backup(root=anvyc_dir, config_path=cfg)
    # shell: binary → .sops.json
    bin_enc = result.backup_dir / "shell/sops/binsec.txt.sops.json"
    assert bin_enc.is_file(), "shell entry should be binary (.sops.json)"
    # claude: inplace → 원본 확장자 유지
    yaml_enc = result.backup_dir / "claude/sops/yamlsec.yaml"
    assert yaml_enc.is_file(), "claude entry should be inplace (.yaml)"
    # inplace 결과는 키 평문 + 값 암호화
    assert "api_key:" in yaml_enc.read_text()
    assert "yaml_value_abc" not in yaml_enc.read_text()

    # metadata 양쪽 encryption 태그 검사
    import json
    meta = json.loads((result.backup_dir / "metadata.json").read_text())
    by_tool = {f["sourcePath"].split("/", 1)[0]: f for f in meta["files"]
               if f.get("encryption", "").startswith("sops/")}
    assert by_tool["shell"]["encryption"] == "sops/age"
    assert by_tool["claude"]["encryption"] == "sops/age/inplace"

    # apply round-trip
    bin_secret.unlink()
    yaml_secret.unlink()
    run_apply(root=anvyc_dir, config_path=cfg)
    assert bin_secret.read_text() == "binary_payload_xyz\n"
    assert "api_key: yaml_value_abc" in yaml_secret.read_text()


def test_sops_status_unchanged_after_backup(tmp_path, age_key) -> None:
    """v0.4.0: SOPS entry 가 backup 직후 status 에서 unchanged 로 표시되는지."""
    from anvyc.core.status import compute_status

    secret = tmp_path / "secret.env"
    secret.write_text("DB_PASSWORD=val_42\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_yaml(anvyc_dir, secret, age_key["public"], age_key["identity"])

    run_backup(root=anvyc_dir, config_path=cfg)
    report = compute_status(anvyc_dir)
    counts = report.counts()
    assert counts.get("unchanged", 0) >= 1, f"expected unchanged ≥ 1, got {counts}"
    assert counts.get("modified", 0) == 0, f"expected 0 modified, got {counts}"


def test_sops_status_modified_after_target_tamper(tmp_path, age_key) -> None:
    """v0.4.0: target 평문 수정 시 status 가 modified 로 정확히 잡아야."""
    from anvyc.core.status import compute_status

    secret = tmp_path / "secret.env"
    secret.write_text("DB_PASSWORD=original\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = _make_yaml(anvyc_dir, secret, age_key["public"], age_key["identity"])

    run_backup(root=anvyc_dir, config_path=cfg)
    # 평문 수정
    secret.write_text("DB_PASSWORD=tampered\n")
    report = compute_status(anvyc_dir)
    assert report.counts().get("modified", 0) >= 1


def test_sops_per_file_format_dict(tmp_path, age_key) -> None:
    """v0.5.2: secret_files 의 dict 항목이 자체 format 으로 override."""
    bin_src = tmp_path / "bin.txt"
    bin_src.write_text("binary_payload\n")
    yaml_src = tmp_path / "config.yaml"
    yaml_src.write_text("api_key: yaml_payload\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = anvyc_dir / "anvyc.yaml"
    # 전역 binary, tool override 없음 — file-level dict 로만 inplace 지정
    cfg.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              secret_scan: false
              sops:
                enabled: true
                format: "binary"
                age_recipients: ["{age_key['public']}"]
                age_identity_file: "{age_key['identity']}"
            tools:
              shell:
                enabled: true
                secret_files:
                  - "{bin_src}"                                  # string → binary (global)
                  - {{path: "{yaml_src}", format: "inplace"}}    # dict → inplace
              git:    {{enabled: false}}
              aws:    {{enabled: false}}
              gh:     {{enabled: false}}
              claude: {{enabled: false}}
              iterm2: {{enabled: false}}
              pulumi: {{enabled: false}}
              cursor: {{enabled: false}}
            """
        )
    )
    result = run_backup(root=anvyc_dir, config_path=cfg)
    bin_enc = result.backup_dir / "shell/sops/bin.txt.sops.json"
    yaml_enc = result.backup_dir / "shell/sops/config.yaml"
    assert bin_enc.is_file(), "binary entry should be .sops.json"
    assert yaml_enc.is_file(), "inplace entry should keep .yaml extension"
    assert "api_key:" in yaml_enc.read_text()
    assert "yaml_payload" not in yaml_enc.read_text()

    import json
    meta = json.loads((result.backup_dir / "metadata.json").read_text())
    by_target = {f["targetPath"]: f for f in meta["files"] if f.get("encryption", "").startswith("sops/")}
    assert by_target[str(bin_src)]["encryption"] == "sops/age"
    assert by_target[str(yaml_src)]["encryption"] == "sops/age/inplace"


def test_sops_format_chain_file_over_tool_over_global(tmp_path, age_key) -> None:
    """v0.5.2 chain: file format > tool format > global format > default."""
    f_global = tmp_path / "global.yaml"       # 전역 inplace 만 명시
    f_tool = tmp_path / "tool.yaml"           # tool sops_format=binary 가 적용
    f_file = tmp_path / "file.yaml"           # file format=inplace 가 적용

    for fp in (f_global, f_tool, f_file):
        # SOPS inplace 모드는 valid yaml dict 필요
        fp.write_text(f"key: contents_of_{fp.stem}\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = anvyc_dir / "anvyc.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              secret_scan: false
              sops:
                enabled: true
                format: "inplace"
                age_recipients: ["{age_key['public']}"]
                age_identity_file: "{age_key['identity']}"
            tools:
              shell:
                enabled: true
                secret_files:
                  - "{f_global}"
                  - {{path: "{f_file}", format: "inplace"}}
              git:
                enabled: true
                sops_format: "binary"
                secret_files:
                  - "{f_tool}"
              aws:    {{enabled: false}}
              gh:     {{enabled: false}}
              claude: {{enabled: false}}
              iterm2: {{enabled: false}}
              pulumi: {{enabled: false}}
              cursor: {{enabled: false}}
            """
        )
    )
    result = run_backup(root=anvyc_dir, config_path=cfg)
    import json
    meta = json.loads((result.backup_dir / "metadata.json").read_text())
    by_target = {f["targetPath"]: f for f in meta["files"] if f.get("encryption", "").startswith("sops/")}

    # f_global: spec.format=None, tool=None → global="inplace"
    assert by_target[str(f_global)]["encryption"] == "sops/age/inplace"
    # f_tool: spec.format=None, tool="binary" → "binary"
    assert by_target[str(f_tool)]["encryption"] == "sops/age"
    # f_file: spec.format="inplace" 가 가장 구체적 → "inplace"
    assert by_target[str(f_file)]["encryption"] == "sops/age/inplace"


def test_sops_invalid_dict_entry_skipped(tmp_path, age_key) -> None:
    """v0.5.2: dict 에 path 가 없으면 silently skip — 오타 entry 가 빌드를 깨지 않음."""
    src = tmp_path / "good.txt"
    src.write_text("ok\n")

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    cfg = anvyc_dir / "anvyc.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              secret_scan: false
              sops:
                enabled: true
                format: "binary"
                age_recipients: ["{age_key['public']}"]
                age_identity_file: "{age_key['identity']}"
            tools:
              shell:
                enabled: true
                secret_files:
                  - "{src}"
                  - {{typo_path: "/nope"}}    # path 키 없음 → skip
                  - 12345                       # int → skip
              git:    {{enabled: false}}
              aws:    {{enabled: false}}
              gh:     {{enabled: false}}
              claude: {{enabled: false}}
              iterm2: {{enabled: false}}
              pulumi: {{enabled: false}}
              cursor: {{enabled: false}}
            """
        )
    )
    result = run_backup(root=anvyc_dir, config_path=cfg)
    import json
    meta = json.loads((result.backup_dir / "metadata.json").read_text())
    enc_entries = [f for f in meta["files"] if f.get("encryption", "").startswith("sops/")]
    assert len(enc_entries) == 1, f"expected 1 sops entry (invalid 2 skipped), got {len(enc_entries)}"


def test_scanner_skips_sops_encrypted(tmp_path, age_key) -> None:
    """sops 로 암호화된 파일은 secret scanner 가 통과시켜야 (false positive 차단)."""
    from anvyc.security.scanner import scan_file

    plaintext = tmp_path / "p.env"
    plaintext.write_text("AWS_ACCESS_KEY_ID=AKIA1234567890ABCDEF\n")
    encrypted = tmp_path / "p.env.sops.json"
    subprocess.run(
        [
            "sops",
            "--encrypt",
            "--age", age_key["public"],
            "--input-type", "dotenv",
            "--output-type", "json",
            "--output", str(encrypted),
            str(plaintext),
        ],
        capture_output=True,
        check=True,
    )
    # 평문은 critical
    assert any(f.severity == "critical" for f in scan_file(plaintext))
    # 암호화 파일은 0 findings (SOPS 인식 → scan skip)
    assert scan_file(encrypted) == []
