"""权限模型：allow / deny / ask，按工具 glob + 路径规则匹配。

P1 只实现判定函数；ask 的阻塞审批语义在 P2（当前由运行时自动放行并记录事件）。
"""

from __future__ import annotations

import fnmatch

from mira.core.config.schemas import ApprovalMode, PermissionRule


class PermissionAction(str):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


def _matches(pattern: str, name: str) -> bool:
    """通配匹配：fnmatch + 尾部 `_*` / `.*` 规则同时匹配裸名（如 `shell_*` → `shell`）。"""
    if fnmatch.fnmatch(name, pattern):
        return True
    if pattern.endswith("_*") and name == pattern[:-2]:
        return True
    return False


class PermissionChecker:
    """基于规则列表 + 审批模式计算某次工具调用的动作。

    - deny 是硬性拦截，任何审批模式下都生效；
    - ask 的解析由审批模式决定（auto→放行 / ask→询问 / deny→拒绝）；
    - 未命中规则时默认允许。
    """

    def __init__(
        self,
        rules: list[PermissionRule] | None = None,
        mode: ApprovalMode = ApprovalMode.ASK,
    ) -> None:
        self.rules = list(rules or [])
        self.mode = mode

    def check(self, tool_name: str, path: str | None = None) -> str:
        """返回 allow / ask / deny。"""
        if self.mode == ApprovalMode.ALLOW_ALL:  # 全部通过：所有调用一律放行
            return PermissionAction.ALLOW
        matched: list[PermissionRule] = []
        for rule in self.rules:
            if not _matches(rule.tool, tool_name):
                continue
            if rule.path != "**":
                if not path or not _matches(rule.path, path):
                    continue
            matched.append(rule)
        if not matched:
            return PermissionAction.ALLOW

        action = matched[-1].action
        if action == PermissionAction.DENY:  # 硬性拦截
            return PermissionAction.DENY
        if action == PermissionAction.ALLOW:  # 显式允许
            return PermissionAction.ALLOW
        # 命中的是 ask：按审批模式解析
        if self.mode == ApprovalMode.AUTO:
            # 自动审批：交由 approver 决策 agent 评估（放行/拒绝/回退人工）；不再直接放行
            return PermissionAction.ASK
        if self.mode == ApprovalMode.DENY:
            return PermissionAction.DENY
        return PermissionAction.ASK
