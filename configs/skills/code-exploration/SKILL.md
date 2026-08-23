---
name: code-exploration
description: 只读调查代码库与 git 历史，输出现状总结
type: prompt
whenToUse: 需要了解代码库现状、调查实现或追溯 git 历史时使用
tools:
- file_read
- search_grep
- git_log
---
只读调查：读关键文件与 git 历史，输出：

- 现状总结
- 关键代码位置
- 与目标的差距
