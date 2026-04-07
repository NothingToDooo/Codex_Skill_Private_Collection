# Codex Skills

一个面向 Codex 的自定义 skill 集合仓库。

这个目录会持续收纳可独立使用的 skill。当前仓库不是单一 skill 的根目录，而是多个 skill 的聚合目录，后续可以继续在这里新增别的 skill。

## 当前包含

### `codex-project-agents-learning`

一个面向 Codex 的项目级记忆整理工具，用来从当前项目的对话 transcript 中提炼可复用规则，并更新项目内的 `AGENTS.md`。

主要能力：

- 扫描属于当前项目的 Codex transcript
- 增量聚合本轮新增或变化的会话
- 生成 `.agents/state/memory-candidates.json`
- 辅助将长期有效的信息整理回 `AGENTS.md`

适用范围：

- 只适配 Windows 环境
- 只面向 Codex 使用
- 不会自动运行，必须手动触发

## 目录结构

当前结构如下：

```text
skills/
├── README.md
└── codex-project-agents-learning/
    ├── agents/
    │   └── openai.yaml
    ├── scripts/
    │   └── project_agents_learning.py
    ├── SKILL.md
```

## 使用方式

以 `codex-project-agents-learning` 为例，实际执行时由 Agent 按该目录下的 `SKILL.md` 定义流程运行 `scripts/project_agents_learning.py`，并处理目标项目里的 `AGENTS.md`。

## `codex-project-agents-learning` 输出

该 skill 运行后会在目标项目中写入或更新：

- `AGENTS.md`
- `.agents/state/agents-learning-index.json`
- `.agents/state/memory-candidates.json`

## 说明

- 这个仓库的根 README 负责介绍整个 skills 集合
- 每个 skill 的具体行为、限制和执行流程，以各自目录中的 `SKILL.md` 为准
