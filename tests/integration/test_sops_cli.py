"""anvyc sops {encrypt|decrypt|rotate-keys} CLI 검증."""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _have_sops_age() -> bool:
    return shutil.which("sops") is not None and shutil.which("age") is not None


pytestmark = pytest.mark.skipif(
    not _have_sops_age(), reason="sops or age binary not installed"
)


@pytest.fixture
def age_key(tmp_path: Path) -> dict:
    identity = tmp_path / "age-key.txt"
    result = subprocess.run(
        ["age-keygen", "-o", str(identity)],
        capture_output=True,
        text=True,
        check=True,
    )
    pub_line = next(
        (l for l in result.stderr.splitlines() if l.startswith("Public key:")),
        "",
    )
    public = pub_line.split(":", 1)[1].strip()
    return {"identity": identity, "public": public}


def _write_yaml(path: Path, age_pub: str, identity_file: Path, fmt: str = "binary") -> None:
    path.write_text(
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
                format: "{fmt}"
                age_recipients: ["{age_pub}"]
                age_identity_file: "{identity_file}"
            tools:
              shell:  {{enabled: false}}
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


def _anvyc(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    cmd = [str(Path(sys.executable).parent / "anvyc"), *args]
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def test_sops_encrypt_creates_default_output(tmp_path, age_key) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write_yaml(cfg, age_key["public"], age_key["identity"])
    src = tmp_path / "secret.env"
    src.write_text("DB=secret_value_123\n")

    proc = _anvyc("sops", "encrypt", str(src), "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"

    # default output: src.env.sops.json
    expected_out = src.with_suffix(src.suffix + ".sops.json")
    assert expected_out.is_file()
    # 평문 부재 확인
    assert "secret_value_123" not in expected_out.read_text()


def test_sops_decrypt_to_stdout(tmp_path, age_key) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write_yaml(cfg, age_key["public"], age_key["identity"])
    src = tmp_path / "x.env"
    src.write_text("KEY=val\n")
    _anvyc("sops", "encrypt", str(src), "--config", str(cfg), cwd=tmp_path)
    enc = src.with_suffix(src.suffix + ".sops.json")

    proc = _anvyc("sops", "decrypt", str(enc), "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "KEY=val" in proc.stdout


def test_sops_decrypt_to_file(tmp_path, age_key) -> None:
    cfg = tmp_path / "anvyc.yaml"
    _write_yaml(cfg, age_key["public"], age_key["identity"])
    src = tmp_path / "x.env"
    src.write_text("FOO=bar\n")
    _anvyc("sops", "encrypt", str(src), "--config", str(cfg), cwd=tmp_path)
    enc = src.with_suffix(src.suffix + ".sops.json")
    out = tmp_path / "out.env"

    proc = _anvyc("sops", "decrypt", str(enc), "-o", str(out), "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0
    assert out.read_text() == "FOO=bar\n"


def test_sops_rotate_keys_with_new_recipient(tmp_path, age_key) -> None:
    """v0.5 핵심: rotate 후 새 키로만 복호화 가능."""
    from anvyc.core.backup import run_backup
    from anvyc.core.sops import SopsError
    from anvyc.core.sops import decrypt as sops_decrypt

    # 초기 anvyc.yaml — 1 recipient (old key)
    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    secret = tmp_path / "secret.env"
    secret.write_text("ROTATE_KEY_TEST=v1\n")
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
                secret_files: ["{secret}"]
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
    run_backup(root=anvyc_dir, config_path=cfg)

    # 새 age key 페어 생성
    new_identity = tmp_path / "age-new.txt"
    r = subprocess.run(
        ["age-keygen", "-o", str(new_identity)], capture_output=True, text=True, check=True
    )
    new_pub = next(
        l for l in r.stderr.splitlines() if l.startswith("Public key:")
    ).split(":", 1)[1].strip()

    # yaml 갱신 — old + new recipient 둘 다, identity 는 new (old 키 잃은 시나리오 흉내X)
    cfg.write_text(
        cfg.read_text().replace(
            f'["{age_key["public"]}"]',
            f'["{new_pub}"]',  # old 제거하고 new 만
        )
    )

    # rotate
    proc = _anvyc("sops", "rotate-keys", "--root", str(anvyc_dir),
                  "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    assert "rotated" in proc.stdout

    # 새 키로 decrypt 가능
    enc = next(anvyc_dir.rglob("secret.env.sops.json"))
    plain_out = tmp_path / "out.env"
    sops_decrypt(enc, plain_out, identity_file=new_identity)
    assert plain_out.read_text() == "ROTATE_KEY_TEST=v1\n"

    # old 키로는 decrypt 불가
    with pytest.raises(SopsError):
        sops_decrypt(enc, tmp_path / "out2.env", identity_file=age_key["identity"])


def test_sops_rotate_dry_run_no_changes(tmp_path, age_key) -> None:
    from anvyc.core.backup import run_backup

    anvyc_dir = tmp_path / ".anvyc"
    for sub in ("backups", "local-backups", "reports"):
        (anvyc_dir / sub).mkdir(parents=True)
    secret = tmp_path / "secret.env"
    secret.write_text("DRYRUN=1\n")
    cfg = anvyc_dir / "anvyc.yaml"
    cfg.write_text(
        textwrap.dedent(
            f"""\
            version: 1
            storage:
              root: ".anvyc"
            security:
              sops:
                enabled: true
                format: "binary"
                age_recipients: ["{age_key['public']}"]
                age_identity_file: "{age_key['identity']}"
            tools:
              shell:
                enabled: true
                secret_files: ["{secret}"]
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
    run_backup(root=anvyc_dir, config_path=cfg)
    enc = next(anvyc_dir.rglob("secret.env.sops.json"))
    mtime_before = enc.stat().st_mtime
    sha_before = enc.read_bytes()

    proc = _anvyc("sops", "rotate-keys", "--root", str(anvyc_dir),
                  "--dry-run", "--config", str(cfg), cwd=tmp_path)
    assert proc.returncode == 0
    assert "would-rotate" in proc.stdout

    assert enc.stat().st_mtime == mtime_before, "dry-run modified mtime"
    assert enc.read_bytes() == sha_before, "dry-run modified content"
