"""Doctor orchestrator.

DESIGN.md §27 참고. 등록된 Check 들을 실행하고 결과를 형식화한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from anvyc.checks.adapter_validate import AdapterValidationCheck
from anvyc.checks.aws_profile_status import AwsProfileStatusCheck
from anvyc.checks.base import Check, CheckContext, CheckResult, Severity
from anvyc.checks.cost_aws_explorer_iam import CostAwsExplorerIamCheck
from anvyc.checks.cost_github_pat_scope import CostGithubPatScopeCheck
from anvyc.checks.creds_expiry import CredsExpiryWithin7dCheck
from anvyc.checks.cross_user import CrossUserCheck
from anvyc.checks.cursor_projects_suggest import CursorProjectsSuggestCheck
from anvyc.checks.hook_integrity import HookIntegrityRiskGateCheck
from anvyc.checks.mcp_extra_importable import McpExtraImportableCheck
from anvyc.checks.mcp_tokens import McpTokensWarnCheck
from anvyc.checks.multi_account_detected import MultiAccountDetectedCheck
from anvyc.checks.op_references import OpReferencesCheck
from anvyc.checks.project_aws_profile import ProjectAwsProfileMappingCheck
from anvyc.checks.project_claude_account import ProjectClaudeAccountMappingCheck
from anvyc.checks.project_gh_account import ProjectGhAccountMappingCheck
from anvyc.checks.project_pulumi_backend import ProjectPulumiBackendMappingCheck
from anvyc.checks.sops_keys import SopsKeysCheck
from anvyc.checks.unused_aws_profiles import UnusedAwsProfilesCheck
from anvyc.checks.venv_hidden import VenvHiddenFlagCheck
from anvyc.checks.work_cwd_track import WorkCwdTrackWiredCheck
from anvyc.core.config import build_check_context, load_config


@dataclass
class DoctorReport:
    results: list[CheckResult] = field(default_factory=list)

    def by_severity(self) -> dict[Severity, list[CheckResult]]:
        out: dict[Severity, list[CheckResult]] = {s: [] for s in Severity}
        for r in self.results:
            out[r.severity].append(r)
        return out

    def has_blocking(self) -> bool:
        return any(r.severity.is_blocking for r in self.results)


_REGISTRY: dict[str, Check] = {
    "cross-user": CrossUserCheck(),
    "venv-hidden-flag": VenvHiddenFlagCheck(),
    "op-references-valid": OpReferencesCheck(),
    "adapter-validate": AdapterValidationCheck(),
    "cursor-projects-suggest": CursorProjectsSuggestCheck(),
    "sops-keys-available": SopsKeysCheck(),
    "mcp-tokens-warn": McpTokensWarnCheck(),
    "mcp-extra-importable": McpExtraImportableCheck(),
    "project-aws-profile-mapping": ProjectAwsProfileMappingCheck(),
    "project-gh-account-mapping": ProjectGhAccountMappingCheck(),
    "project-claude-account-mapping": ProjectClaudeAccountMappingCheck(),
    "project-pulumi-backend-mapping": ProjectPulumiBackendMappingCheck(),
    "aws-profile-status": AwsProfileStatusCheck(),
    "multi-account-detected": MultiAccountDetectedCheck(),
    "unused-aws-profiles": UnusedAwsProfilesCheck(),
    "creds-expiry-within-7d": CredsExpiryWithin7dCheck(),
    "cost-aws-explorer-iam": CostAwsExplorerIamCheck(),
    "cost-github-pat-scope": CostGithubPatScopeCheck(),
    "hook-integrity-risk-gate": HookIntegrityRiskGateCheck(),
    "work-cwd-track-wired": WorkCwdTrackWiredCheck(),
}


def run_doctor(
    config_path: Path | None = None,
    *,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    ctx: CheckContext | None = None,
) -> DoctorReport:
    """등록된 Check 들을 실행한다."""
    if ctx is None:
        cfg = load_config(config_path)
        ctx = build_check_context(cfg)

    only_set = set(only) if only else None
    skip_set = set(skip) if skip else set()

    report = DoctorReport()
    for name, check in _REGISTRY.items():
        if only_set is not None and name not in only_set:
            continue
        if name in skip_set:
            continue
        report.results.extend(check.run(ctx))
    return report
