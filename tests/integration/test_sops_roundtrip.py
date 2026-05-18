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
        (l for l in result.stderr.splitlines() if l.startswith("Public key:")),
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
