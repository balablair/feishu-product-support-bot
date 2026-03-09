#!/usr/bin/env python3
"""
飞书智能客服机器人 — 配置向导

首次使用请运行：
    python setup.py
"""

import json
import os
import sys
import time

# ── 自动安装向导依赖 ───────────────────────────────────────────────────────────
def _ensure_deps():
    try:
        import questionary
        import rich
    except ImportError:
        print("正在安装配置向导所需依赖（questionary, rich）...")
        os.system(f'"{sys.executable}" -m pip install questionary rich -q')

_ensure_deps()

import requests
import questionary
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

console = Console()

# ── AI 生成 SOUL.md 的系统提示 ────────────────────────────────────────────────
_SOUL_GEN_SYSTEM = """\
你是一个帮助团队配置飞书客服机器人的专家助手。
根据用户提供的产品信息，生成一个完整、专业的 SOUL.md 文件。

SOUL.md 是机器人的"灵魂文件"，定义了它的身份、语言风格、知识边界和行为规范。

生成要求：
- 使用中文，语气专业友好，像熟悉产品的资深同事
- 能力边界要清晰具体，不要泛泛而谈
- 信息红线部分要结合产品特性定制
- 直接输出 Markdown 内容，不要有任何前缀说明文字

输出结构（严格按此格式）：
# [产品名] Support Bot — SOUL.md

## 1. 身份定义
（一段话说明 bot 是谁、服务什么用户、核心职责是什么）

## 2. 语言与风格
（语言、语气规范，包含好的和不好的回复示例）

## 3. 能力边界

### ✅ 可以回答的问题
（列举 3-5 类可以回答的问题类型）

### ❌ 不应该做的事
（列举 2-3 类明确禁止的行为）

## 4. 信息红线（严格遵守）
（不得透露的内容，以及被问到时的标准回答）

## 5. 反馈收集引导
（遇到 Bug 报告、功能建议时的标准引导流程）

## 6. 行为约束总结
（3-5 条核心原则，简洁直接）"""


_SOUL_GEN_USER_TEMPLATE = """\
请根据以下信息生成 SOUL.md：

产品名称：{product_name}

产品描述：
{description}

目标用户：
{users}

机器人应该能回答的问题范围：
{can_answer}

机器人不应该涉及的内容：
{cannot_answer}

其他补充：
{extra}"""


# ── 工具函数 ───────────────────────────────────────────────────────────────────
def _print_step(n: int, total: int, title: str):
    console.print(f"\n[bold cyan][{n}/{total}][/bold cyan] [bold]{title}[/bold]")
    console.print("─" * 50, style="dim")


def _ok(msg: str):
    console.print(f"  [green]✓[/green] {msg}")


def _warn(msg: str):
    console.print(f"  [yellow]![/yellow] {msg}")


def _err(msg: str):
    console.print(f"  [red]✗[/red] {msg}")


def _test_feishu(app_id: str, app_secret: str) -> bool:
    """测试飞书应用凭证是否有效"""
    try:
        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 0:
            return True
        _err(f"飞书验证失败：{data.get('msg', '未知错误')}")
        return False
    except Exception as e:
        _err(f"无法连接飞书服务器：{e}")
        return False


def _test_openai(api_key: str, api_url: str, model: str) -> bool:
    """测试 AI API 是否有效"""
    try:
        resp = requests.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.HTTPError as e:
        _err(f"API 认证失败（HTTP {e.response.status_code}），请检查 API Key")
        return False
    except Exception as e:
        _err(f"无法连接 AI 服务：{e}")
        return False


def _call_ai(api_key: str, api_url: str, model: str, system: str, user: str) -> str:
    """调用 AI，返回文本结果"""
    resp = requests.post(
        api_url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _generate_soul(api_key: str, api_url: str, model: str, answers: dict) -> str:
    """用 AI 生成 SOUL.md 内容"""
    user_prompt = _SOUL_GEN_USER_TEMPLATE.format(**answers)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        progress.add_task("AI 正在生成 SOUL.md，请稍候...", total=None)
        soul = _call_ai(api_key, api_url, model, _SOUL_GEN_SYSTEM, user_prompt)
    return soul


def _write_env(config: dict):
    """将配置写入 .env 文件"""
    lines = [
        "# 由 setup.py 向导自动生成\n",
        "\n# ── 飞书应用凭证 ────────────────────────────────────\n",
        f"FEISHU_APP_ID={config['feishu_app_id']}\n",
        f"FEISHU_APP_SECRET={config['feishu_app_secret']}\n",
        "\n# ── 产品名称 ─────────────────────────────────────────\n",
        f"PRODUCT_NAME={config['product_name']}\n",
        "\n# ── 文字对话 AI ──────────────────────────────────────\n",
        f"OPENAI_API_KEY={config['openai_api_key']}\n",
        f"OPENAI_API_URL={config['openai_api_url']}\n",
        f"OPENAI_MODEL={config['openai_model']}\n",
    ]

    if config.get("vision_api_key"):
        lines += [
            "\n# ── 图片理解 AI ──────────────────────────────────────\n",
            f"VISION_API_KEY={config['vision_api_key']}\n",
        ]

    if config.get("bitable_app_token"):
        lines += [
            "\n# ── 飞书多维表格（反馈收集）────────────────────────\n",
            f"BITABLE_APP_TOKEN={config['bitable_app_token']}\n",
            f"BITABLE_TABLE_ID={config['bitable_table_id']}\n",
        ]
        if config.get("feedback_assignee"):
            lines.append(f"FEEDBACK_DEFAULT_ASSIGNEE={config['feedback_assignee']}\n")

    if config.get("feishu_doc_tokens"):
        lines += [
            "\n# ── 飞书云文档知识库 ────────────────────────────────\n",
            f"FEISHU_DOC_TOKENS={config['feishu_doc_tokens']}\n",
        ]

    if config.get("feishu_wiki_token"):
        lines += [
            "\n# ── 飞书 Wiki Space 知识库 ──────────────────────────\n",
            f"FEISHU_WIKI_TOKEN={config['feishu_wiki_token']}\n",
        ]

    if config.get("embedding_api_key"):
        lines += [
            "\n# ── RAG 向量检索 ─────────────────────────────────────\n",
            f"EMBEDDING_API_KEY={config['embedding_api_key']}\n",
        ]

    if config.get("admin_open_ids"):
        lines += [
            "\n# ── 管理员（可使用 /reload 等指令）─────────────────\n",
            f"ADMIN_OPEN_IDS={config['admin_open_ids']}\n",
        ]

    with open(".env", "w", encoding="utf-8") as f:
        f.writelines(lines)


# ── 主向导流程 ────────────────────────────────────────────────────────────────
def main():
    console.print(Panel.fit(
        "[bold cyan]飞书智能客服机器人[/bold cyan]\n"
        "[dim]配置向导 — 约需 5 分钟[/dim]",
        border_style="cyan",
    ))
    console.print()

    config = {}
    TOTAL_STEPS = 5

    # ──────────────────────────────────────────────────────────────────────────
    # Step 1: 飞书应用凭证
    # ──────────────────────────────────────────────────────────────────────────
    _print_step(1, TOTAL_STEPS, "飞书应用配置")
    console.print(
        "  [dim]前往 https://open.feishu.cn/app 创建企业自建应用，\n"
        "  在「凭证与基础信息」中获取 App ID 和 App Secret。\n"
        "  确保已在「事件与回调」中开启[bold]长连接模式[/bold]。[/dim]\n"
    )

    while True:
        app_id = questionary.text("  App ID：", style=questionary.Style([("answer", "cyan")])).ask()
        app_secret = questionary.password("  App Secret：").ask()
        if not app_id or not app_secret:
            sys.exit(0)

        with Progress(SpinnerColumn(), TextColumn("  正在测试飞书连接..."), transient=True) as p:
            p.add_task("", total=None)
            ok = _test_feishu(app_id.strip(), app_secret.strip())

        if ok:
            _ok("飞书连接成功")
            config["feishu_app_id"] = app_id.strip()
            config["feishu_app_secret"] = app_secret.strip()
            break
        else:
            if not questionary.confirm("  重新输入？").ask():
                sys.exit(1)

    # ──────────────────────────────────────────────────────────────────────────
    # Step 2: AI 模型配置
    # ──────────────────────────────────────────────────────────────────────────
    _print_step(2, TOTAL_STEPS, "AI 模型配置")
    console.print("  [dim]支持任何 OpenAI 兼容 API，推荐 DeepSeek（性价比最高）。[/dim]\n")

    PRESETS = {
        "DeepSeek（推荐）": ("https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
        "OpenAI": ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
        "Moonshot（月之暗面）": ("https://api.moonshot.cn/v1/chat/completions", "moonshot-v1-8k"),
        "智谱 GLM": ("https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm-4-flash"),
        "自定义": (None, None),
    }

    provider = questionary.select(
        "  选择 AI 服务商：",
        choices=list(PRESETS.keys()),
    ).ask()

    if provider == "自定义":
        api_url = questionary.text("  API URL：").ask().strip()
        model = questionary.text("  模型名称：").ask().strip()
    else:
        api_url, model = PRESETS[provider]

    api_key = questionary.password("  API Key：").ask()
    if not api_key:
        sys.exit(0)
    api_key = api_key.strip()

    with Progress(SpinnerColumn(), TextColumn("  正在测试 AI 连接..."), transient=True) as p:
        p.add_task("", total=None)
        ok = _test_openai(api_key, api_url, model)

    if ok:
        _ok(f"AI 连接成功（{model}）")
    else:
        _warn("AI 连接测试失败，但将继续配置。请检查 API Key 后重新运行向导。")

    config["openai_api_key"] = api_key
    config["openai_api_url"] = api_url
    config["openai_model"] = model

    # ──────────────────────────────────────────────────────────────────────────
    # Step 3: AI 对话生成 SOUL.md
    # ──────────────────────────────────────────────────────────────────────────
    _print_step(3, TOTAL_STEPS, "用 AI 生成机器人人格（SOUL.md）")
    console.print(
        "  [dim]回答几个问题，AI 会自动生成适合你产品的 SOUL.md。\n"
        "  这决定了机器人的身份、语气和知识边界。[/dim]\n"
    )

    soul_answers = {}

    product_name = questionary.text("  你的产品叫什么名字？").ask()
    if not product_name:
        sys.exit(0)
    soul_answers["product_name"] = product_name.strip()
    config["product_name"] = product_name.strip()

    soul_answers["description"] = questionary.text(
        "  用 2-3 句话描述你的产品是做什么的：",
        multiline=False,
    ).ask() or "一款 AI 产品"

    soul_answers["users"] = questionary.text(
        "  机器人主要服务哪些用户？（如：内部员工、付费客户、beta 测试用户）",
    ).ask() or "产品用户"

    soul_answers["can_answer"] = questionary.text(
        "  机器人应该能回答哪些类型的问题？（如：产品使用方法、功能介绍、报错排查）",
    ).ask() or "产品使用相关问题"

    soul_answers["cannot_answer"] = questionary.text(
        "  有哪些内容机器人不应该涉及？（如：竞品对比、底层技术、商业信息）",
    ).ask() or "竞品、商业数据、未发布功能"

    soul_answers["extra"] = questionary.text(
        "  还有什么补充？（没有可直接回车跳过）",
    ).ask() or "无"

    # 生成并循环确认
    soul_content = None
    iteration = 0
    while True:
        try:
            soul_content = _generate_soul(api_key, api_url, model, soul_answers)
        except Exception as e:
            _err(f"AI 生成失败：{e}")
            if not questionary.confirm("  重试？").ask():
                soul_content = open("SOUL.md").read() if os.path.exists("SOUL.md") else ""
                break
            continue

        console.print()
        console.print(Panel(
            Markdown(soul_content),
            title="[cyan]生成的 SOUL.md 预览[/cyan]",
            border_style="dim",
        ))

        action = questionary.select(
            "  对这个结果满意吗？",
            choices=[
                "满意，保存并继续",
                "重新生成（告诉 AI 哪里需要改）",
                "跳过，我之后手动编辑",
            ],
        ).ask()

        if action == "满意，保存并继续":
            break
        elif action == "跳过，我之后手动编辑":
            soul_content = None
            break
        else:
            iteration += 1
            feedback = questionary.text(
                f"  告诉 AI 需要改什么（第 {iteration} 次修改）：",
            ).ask() or ""
            soul_answers["extra"] = (soul_answers.get("extra", "") + f"\n修改要求：{feedback}").strip()

    if soul_content:
        with open("SOUL.md", "w", encoding="utf-8") as f:
            f.write(soul_content)
        _ok("SOUL.md 已保存")
    else:
        _warn("跳过 SOUL.md 生成，请稍后手动编辑")

    # ──────────────────────────────────────────────────────────────────────────
    # Step 4: 可选功能
    # ──────────────────────────────────────────────────────────────────────────
    _print_step(4, TOTAL_STEPS, "可选功能配置")

    # 图片理解
    if questionary.confirm("  启用图片理解？（用户发送截图时自动分析报错）", default=False).ask():
        console.print("  [dim]使用阿里云百炼 Qwen-VL，需在 https://bailian.console.aliyun.com/ 申请 API Key[/dim]")
        vision_key = questionary.password("  阿里云 API Key：").ask()
        config["vision_api_key"] = (vision_key or "").strip()
        _ok("图片理解已启用")
    else:
        config["vision_api_key"] = ""

    # 反馈收集到 Bitable
    console.print()
    if questionary.confirm("  启用用户反馈自动收集到飞书多维表格？", default=False).ask():
        console.print(
            "  [dim]在飞书多维表格创建一张新表，包含字段：反馈内容、用户、问题分类、状态、反馈日期、回复内容\n"
            "  从表格 URL 中获取 app_token（https://xxx.feishu.cn/base/[app_token]/...）\n"
            "  和 table_id（URL 末尾的 tbl... 部分）[/dim]\n"
        )
        config["bitable_app_token"] = questionary.text("  Bitable App Token：").ask().strip()
        config["bitable_table_id"] = questionary.text("  Table ID：").ask().strip()
        config["feedback_assignee"] = (questionary.text("  默认负责人 open_id（可留空）：").ask() or "").strip()
        _ok("反馈收集已启用（bot 首次启动时将自动创建所需字段，无需手动配置表格列）")
    else:
        config["bitable_app_token"] = ""
        config["bitable_table_id"] = ""

    # 飞书云文档
    console.print()
    if questionary.confirm("  配置飞书云文档作为知识库？（指定单个/多个文档 token）", default=False).ask():
        console.print("  [dim]从文档 URL 中获取 token 部分，多个文档用英文逗号分隔[/dim]")
        config["feishu_doc_tokens"] = questionary.text("  文档 Token（逗号分隔）：").ask().strip()
        _ok("云文档知识库已配置")
    else:
        config["feishu_doc_tokens"] = ""

    # Wiki Space 知识库
    console.print()
    if questionary.confirm("  配置飞书 Wiki Space 作为知识库？（自动加载整个 Space 的所有文档）", default=False).ask():
        console.print(
            "  [dim]从 Wiki 页面 URL 末尾获取 token，例如：\n"
            "  https://xxx.feishu.cn/wiki/[bold]YLaCwu5OgiF1UGkEF2gcQTKkn8b[/bold]\n"
            "  所需额外操作：① 开通 wiki:wiki:readonly 权限；② 在 Wiki 设置中添加机器人为成员[/dim]\n"
        )
        config["feishu_wiki_token"] = questionary.text("  Wiki 页面 Token：").ask().strip()
        _ok("Wiki Space 知识库已配置")
    else:
        config["feishu_wiki_token"] = ""

    # RAG 向量检索
    console.print()
    # 如果已配置 vision_api_key，提示复用
    has_vision = bool(config.get("vision_api_key"))
    rag_hint = "（将复用已配置的阿里云 API Key）" if has_vision else "（需要阿里云百炼 API Key，与图片理解共用同一账号）"
    if questionary.confirm(f"  启用 RAG 向量检索？{rag_hint} 知识库较大时强烈推荐", default=True).ask():
        if has_vision:
            config["embedding_api_key"] = config["vision_api_key"]
            _ok("RAG 已启用，复用阿里云 API Key")
        else:
            console.print("  [dim]前往 https://bailian.console.aliyun.com/ 申请 API Key[/dim]")
            emb_key = questionary.password("  阿里云 API Key：").ask()
            config["embedding_api_key"] = (emb_key or "").strip()
            _ok("RAG 向量检索已启用")
    else:
        config["embedding_api_key"] = ""
        _warn("未启用 RAG，将使用全量知识库模式（知识库较大时会消耗更多 token）")

    # 管理员
    console.print()
    if questionary.confirm("  配置管理员？（管理员可在群内发送 /reload 热更新知识库）", default=False).ask():
        console.print("  [dim]在飞书中打开对方名片，或通过 API 获取 open_id（格式：ou_xxx），多个用逗号分隔[/dim]")
        config["admin_open_ids"] = questionary.text("  管理员 open_id（逗号分隔）：").ask().strip()
        _ok("管理员已配置")
    else:
        config["admin_open_ids"] = ""

    # ──────────────────────────────────────────────────────────────────────────
    # Step 5: 写入配置文件
    # ──────────────────────────────────────────────────────────────────────────
    _print_step(5, TOTAL_STEPS, "保存配置")

    _write_env(config)
    _ok(".env 文件已生成")

    # 完成
    console.print()
    console.print(Panel.fit(
        "[bold green]配置完成！[/bold green]\n\n"
        "启动机器人：\n"
        "  [cyan]python app.py[/cyan]\n\n"
        "如需修改机器人人格：编辑 [cyan]SOUL.md[/cyan]\n"
        "如需添加知识库文档：放入 [cyan]knowledge/[/cyan] 目录\n"
        "如需修改配置：编辑 [cyan].env[/cyan] 或重新运行 [cyan]python setup.py[/cyan]",
        border_style="green",
    ))


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        console.print("\n\n[dim]已取消配置向导。[/dim]")
        sys.exit(0)
