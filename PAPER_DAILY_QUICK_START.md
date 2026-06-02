# Paper Daily & Paper Learning - Quick Start

简化的命令行接口用于运行paper-daily和paper-learning工作流。

## Paper Daily (arXiv Discovery & Publishing)

```bash
# 发现论文（默认：昨天UTC日期）
./run-paper-daily.sh discover

# 为特定日期发现论文
./run-paper-daily.sh discover --date 2026-05-31

# 检查发布状态
./run-paper-daily.sh status --date 2026-05-31

# 增强元数据（获取作者信息等）
./run-paper-daily.sh enrich --date 2026-05-31

# 运行完整日报流程
./run-paper-daily.sh run --date 2026-05-31

# 最终发布到README和feed
./run-paper-daily.sh finalize --date 2026-05-31
```

### 完整工作流示例

```bash
# 1. 发现论文
./run-paper-daily.sh discover --date 2026-05-31

# 2. 增强元数据（需要poppler-utils）
./run-paper-daily.sh enrich --date 2026-05-31

# 3. 检查状态
./run-paper-daily.sh status --date 2026-05-31

# 4. 发布
./run-paper-daily.sh finalize --date 2026-05-31
```

## Paper Learning (Notion Integration & Deep Reading)

```bash
# 运行日报学习管道（发布到Notion）
./run-paper-learning.sh daily --date 2026-05-31

# 试运行（不写入Notion）
./run-paper-learning.sh daily --dry-run

# 处理Notion队列
./run-paper-learning.sh queue

# 触发深度阅读（需要skill context）
./run-paper-learning.sh deep-read 2606.01152 2606.01311

# 检查学习工作流状态
./run-paper-learning.sh status --date 2026-05-31
```

## 推荐工作流

### 日常操作（每天）

```bash
# 早上（自动运行或手动）
./run-paper-daily.sh discover --date $(date -u -d yesterday +%Y-%m-%d)

# 中午
./run-paper-daily.sh enrich --date $(date -u -d yesterday +%Y-%m-%d)
./run-paper-daily.sh finalize --date $(date -u -d yesterday +%Y-%m-%d)

# 下午
./run-paper-learning.sh daily --date $(date -u -d yesterday +%Y-%m-%d)

# 查看Notion Paper Inbox，进行标记和HITL review
```

### 发布特定日期的报告

```bash
# 假设要发布2026-05-31的报告
DATE="2026-05-31"

# 1. 检查是否已有discovered papers
./run-paper-daily.sh status --date $DATE

# 2. 如果没有，运行discovery
./run-paper-daily.sh discover --date $DATE

# 3. 增强元数据
./run-paper-daily.sh enrich --date $DATE

# 4. 最终发布
./run-paper-daily.sh finalize --date $DATE

# 5. 发布到Notion
./run-paper-learning.sh daily --date $DATE
```

## 配置

### Paper Learning 配置

需要 `~/.paper-learning/config.json`:

```bash
# 从示例配置创建
cp skill/paper-learning/templates/config.example.json ~/.paper-learning/config.json

# 编辑配置并填入Notion Token等信息
nano ~/.paper-learning/config.json
```

### 环境变量

可选地创建 `.local/paper-learning.env`:

```bash
# .local/paper-learning.env
export NOTION_TOKEN="your-token"
export FEISHU_TOKEN="your-token"
export DASHSCOPE_API_KEY="your-key"
```

## 常见命令

| 目的 | 命令 |
|------|------|
| 快速发现论文 | `./run-paper-daily.sh discover` |
| 查看发布状态 | `./run-paper-daily.sh status --date 2026-05-31` |
| 完整日报流程 | `./run-paper-daily.sh discover && ./run-paper-daily.sh enrich && ./run-paper-daily.sh finalize` |
| 发布到Notion | `./run-paper-learning.sh daily --date 2026-05-31` |
| 处理Notion队列 | `./run-paper-learning.sh queue` |
| 试运行（不修改文件） | `./run-paper-daily.sh run --view-only` 或 `./run-paper-learning.sh daily --dry-run` |

## 故障排除

### Paper Daily

- **论文发现不完整**: 检查arXiv API响应，可能需要增加 `--budget-seconds`
- **缺少元数据**: 运行 `enrich` 步骤，需要poppler-utils来从PDF提取机构
- **无法发布**: 检查 `status`，确保所有required fields都已填充

### Paper Learning

- **Notion连接失败**: 验证config.json中的NOTION_TOKEN
- **缺少配置**: 确保 `~/.paper-learning/config.json` 存在
- **环境变量未加载**: 创建 `.local/paper-learning.env`

## 相关文件

- `skill/paper-daily/SKILL.md` - 详细的paper-daily工作流文档
- `skill/paper-learning/SKILL.md` - 详细的paper-learning工作流文档
- `CLAUDE.md` - 项目整体指引
