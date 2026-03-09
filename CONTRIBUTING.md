# 贡献指南

欢迎贡献代码、文档或反馈问题！

## 环境准备

```bash
git clone https://github.com/your-org/feishu-support-bot.git
cd feishu-support-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填入测试用的配置
```

## 运行测试

```bash
pytest tests/ -v
```

所有 PR 必须保证测试全部通过。新增功能需附带对应的测试用例。

## 项目结构

```
app.py          # 主逻辑：消息接收、对话历史、回复发送
config.py       # 配置加载（从环境变量读取）
feedback.py     # 反馈识别与多维表格写入
docs.py         # 飞书云文档知识库拉取
setup.py        # CLI 配置向导（含 AI 生成 SOUL.md）
tests/          # 单元测试
```

## 提交 PR 前的检查清单

- [ ] 代码通过 `pytest tests/ -v`
- [ ] 新功能在 README.md 中有对应说明（如需要）
- [ ] 没有提交 `.env` 文件或任何包含真实 API Key 的文件
- [ ] commit message 清晰描述了做了什么、为什么

## 报告 Bug

请在 Issues 中提交，包含：
1. 复现步骤
2. 期望行为 vs 实际行为
3. 运行环境（Python 版本、OS）
4. 相关日志（注意脱敏 API Key）

## 功能建议

欢迎在 Issues 中讨论新功能想法。大的改动建议先开 Issue 讨论方向再动手。
