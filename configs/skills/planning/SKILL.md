---
name: planning
description: 先制定分步计划再执行，复杂/多步任务必用
type: prompt
whenToUse: 遇到复杂或多步任务、需要先规划再执行时使用
tools:
- file_read
- file_write
---
请先制定分步计划再执行：

1. 拆解目标为可验证步骤
2. 预估每步所需工具与风险
3. 执行并逐项核对
4. 汇总结果与偏差
