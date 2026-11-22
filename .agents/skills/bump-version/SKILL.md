---
name: bump-version
description: Update project version across pyproject.toml, mcdreforged.plugin.json, and build_deploy.py, then generate a release note. Use when creating a release branch, bumping version, or when the user mentions release, version bump, or git flow release.
---

# Bump Version

When starting a release (e.g. `git flow release start X.Y.Z`), update the version in all three files and generate a release note.

## Version Locations

| File | Pattern | Example |
|------|---------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` | `version = "2.0.33"` |
| `GUGUbot/mcdreforged.plugin.json` | `"version": "X.Y.Z"` | `"version": "2.0.33"` |
| `tests/build_deploy.py` | `output_filename = "gugubot-vX.Y.Z-beta.mcdr"` | `output_filename = "gugubot-v2.0.33-beta.mcdr"` |

## Workflow

1. **Determine target version**: Extract from release branch name (`release/X.Y.Z`) or user input.
2. **Read each file** to get the current version string.
3. **Replace version** in all three files using exact string replacement:
   - `pyproject.toml`: `version = "OLD"` → `version = "NEW"`
   - `GUGUbot/mcdreforged.plugin.json`: `"version": "OLD"` → `"version": "NEW"`
   - `tests/build_deploy.py`: `output_filename = "gugubot-vOLD-beta.mcdr"` → `output_filename = "gugubot-vNEW-beta.mcdr"`
4. **Verify** by reading all three files to confirm the update.
5. **Generate release note** (see below).
6. **Report** version changes and release note to the user.

## Release Note Generation

After bumping version, generate a concise release note for GitHub Releases.

### Steps

1. Get commits since the last tag:

```bash
git log $(git describe --tags --abbrev=0)..HEAD --oneline
```

2. Classify each commit:

| 类型 | 判断依据 | emoji |
|------|----------|-------|
| ✨ 新功能 | feat、add、新增、支持 | ✨ |
| 🐛 修复 | fix、bug、修复、解决 | 🐛 |
| ⚡ 优化 | perf、optimize、refactor、优化、重构 | ⚡ |
| 📝 文档 | docs、readme、文档 | 📝 |
| 🔧 杂项 | chore、ci、build、style、test 等 | 🔧 |

3. Output format (省略空分类):

```markdown
## What's Changed

### ✨ 新功能
- 一句话描述

### 🐛 修复
- 一句话描述

### ⚡ 优化
- 一句话描述
```

### 写作规则

- 每条一句话，动词开头，不超过 20 字
- 合并相关小 commit，省略纯格式化/重构等无感改动
- 不带 commit hash、不带作者
- 简洁、口语化、用户视角

## Important Notes

- All three files **must** be updated together to keep versions consistent.
- Version format: `MAJOR.MINOR.PATCH` (e.g. `2.0.33`), no `v` prefix in `pyproject.toml` and `mcdreforged.plugin.json`.
- In `build_deploy.py` the version is embedded with `v` prefix and `-beta` suffix.
