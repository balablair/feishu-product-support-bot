"""
飞书群消息监控机器人 - 长连接（WebSocket）模式
使用飞书官方 Python SDK lark-oapi，无需 Flask / ngrok / 公网地址
"""

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from threading import Lock

import requests
import lark_oapi as lark
import base64
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody, GetMessageResourceRequest

from config import Config
from feedback import ai_detect_and_classify, save_feedback, should_reply
from docs import load_feishu_docs

# ── 知识库加载 ────────────────────────────────────────────────────────────────
def _extract_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_pptx(path: Path) -> str:
    from pptx import Presentation
    prs = Presentation(str(path))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text.strip())
        if texts:
            slides.append(f"[第{i}页] " + " ".join(texts))
    return "\n".join(slides)


def _extract_pdf(path: Path) -> str:
    import pdfplumber
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if text and text.strip():
                pages.append(f"[第{i}页] {text.strip()}")
    return "\n".join(pages)


def load_knowledge() -> str:
    """
    读取 knowledge/ 目录下所有文件，合并为一段文本
    支持：.txt .md .docx .pptx .pdf
    启动时加载一次，之后常驻内存
    """
    kb_dir = Path(__file__).parent / "knowledge"
    if not kb_dir.exists():
        return ""

    extractors = {
        ".txt":  lambda f: f.read_text(encoding="utf-8"),
        ".md":   lambda f: f.read_text(encoding="utf-8"),
        ".docx": _extract_docx,
        ".pptx": _extract_pptx,
        ".pdf":  _extract_pdf,
    }

    parts = []
    for f in sorted(kb_dir.glob("**/*")):
        if not f.is_file() or f.suffix not in extractors:
            continue
        try:
            text = extractors[f.suffix](f).strip()
            if text:
                parts.append(f"=== {f.name} ===\n{text}")
                # 日志在 logger 初始化后才能用，这里先跳过
        except Exception as e:
            # 解析失败不影响其他文件
            pass

    return "\n\n".join(parts)

# ── 日志配置 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
# 屏蔽 pdfplumber 的字体解析噪音
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# ── 启动时加载知识库 ──────────────────────────────────────────────────────────
KNOWLEDGE = load_knowledge()
if KNOWLEDGE:
    logger.info(f"本地知识库已加载，共 {len(KNOWLEDGE)} 字符")
else:
    logger.info("knowledge/ 目录为空，未加载本地知识库")

# ── 飞书 SDK 客户端（负责所有 API 调用）──────────────────────────────────────
feishu_client = (
    lark.Client.builder()
    .app_id(Config.FEISHU_APP_ID)
    .app_secret(Config.FEISHU_APP_SECRET)
    .build()
)

# ── 启动时加载飞书云文档知识库 ───────────────────────────────────────────────
_cloud_knowledge = load_feishu_docs(feishu_client)
if _cloud_knowledge:
    KNOWLEDGE = (KNOWLEDGE + "\n\n" + _cloud_knowledge).strip() if KNOWLEDGE else _cloud_knowledge
    logger.info(f"云文档知识库已合并，知识库总计 {len(KNOWLEDGE)} 字符")

# ── 事件去重：避免飞书重复推送被重复处理 ────────────────────────────────────
_processed_events: dict[str, float] = {}
_event_lock = Lock()
EVENT_DEDUPE_TTL = 300  # 秒


def _is_duplicate(event_id: str) -> bool:
    """基于 event_id 去重，TTL 内的相同事件视为重复"""
    now = time.time()
    with _event_lock:
        # 清理过期记录，防止内存无限增长
        expired = [k for k, t in _processed_events.items() if now - t > EVENT_DEDUPE_TTL]
        for k in expired:
            del _processed_events[k]

        if event_id in _processed_events:
            return True
        _processed_events[event_id] = now
        return False


# ── 飞书：发送文本消息 ────────────────────────────────────────────────────────
def send_text_message(chat_id: str, text: str) -> bool:
    """向指定群发送普通文本消息"""
    try:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )
        resp = feishu_client.im.v1.message.create(request)
        if not resp.success():
            logger.error(f"发送消息失败: code={resp.code}, msg={resp.msg}")
            return False
        logger.info(f"消息已发送到群 {chat_id}")
        return True
    except Exception as e:
        logger.error(f"发送消息异常: {e}")
        return False


# ── MiniMax：生成自然对话回复 ─────────────────────────────────────────────────
def _load_soul() -> str:
    """加载 SOUL.md 作为 bot 的人格定义与行为规范"""
    soul_path = Path(__file__).parent / "SOUL.md"
    if soul_path.exists():
        text = soul_path.read_text(encoding="utf-8").strip()
        logger.info("SOUL.md 已加载")
        return text
    logger.warning("未找到 SOUL.md，将使用默认 prompt")
    return "你是一个飞书群助手，请简洁、友好地回复用户消息。"


# 启动时加载 SOUL.md
SOUL_PROMPT = _load_soul()


_NO_MARKDOWN = """
---
【格式要求（必须严格遵守）】
回复内容只能是纯文本。禁止使用任何 Markdown 语法，包括但不限于：
- 加粗（**文字** 或 __文字__）
- 斜体（*文字* 或 _文字_）
- 标题（# ## ###）
- 列表符号（- * 1.）
- 代码块（``` 或 `）
- 分隔线（---）
- 链接格式（[文字](url)）
如果需要列举内容，用"1、2、3、"或换行代替。"""


def _build_system_prompt() -> str:
    """
    组装最终 system prompt：
    SOUL.md（身份/风格/规则）+ knowledge/（产品知识）+ 格式强制要求
    """
    base = SOUL_PROMPT
    if KNOWLEDGE:
        base += "\n\n---\n\n以下是你可以参考的产品知识库内容，回答问题时优先依据此内容：\n\n" + KNOWLEDGE
    return base + _NO_MARKDOWN


def generate_reply(text: str) -> str:
    """
    调用 OpenAI API 生成自然对话回复
    失败时返回兜底回复，保证主流程不中断
    """
    if not Config.OPENAI_API_KEY:
        logger.warning("未配置 OPENAI_API_KEY")
        return "收到，稍后回复你。"

    try:
        resp = requests.post(
            Config.OPENAI_API_URL,
            headers={
                "Authorization": f"Bearer {Config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": Config.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.7,
            },
            timeout=15,
        )
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"AI 回复: {reply}")
        return reply

    except Exception as e:
        logger.error(f"调用 OpenAI API 失败: {e}")
        return "收到，稍后回复你。"


def download_image(message_id: str, image_key: str) -> str | None:
    """从飞书下载图片，返回 base64 字符串，失败返回 None"""
    try:
        req = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(image_key)
            .type("image")
            .build()
        )
        resp = feishu_client.im.v1.message_resource.get(req)
        if not resp.success():
            logger.error(f"图片下载失败: code={resp.code} msg={resp.msg}")
            return None
        return base64.b64encode(resp.file.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"图片下载异常: {e}")
        return None


def generate_reply_with_image(image_b64: str, text: str = "") -> str:
    """调用 Qwen-VL 分析图片"""
    if not Config.VISION_API_KEY:
        return "收到，稍后回复你。"
    try:
        user_content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": text if text else "请描述这张图片的内容，如果是报错截图请帮忙分析问题。"},
        ]
        resp = requests.post(
            Config.VISION_API_URL,
            headers={
                "Authorization": f"Bearer {Config.VISION_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": Config.VISION_MODEL,
                "messages": [
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.7,
            },
            timeout=30,
        )
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        logger.info(f"图片 AI 回复: {reply[:80]}")
        return reply
    except Exception as e:
        logger.error(f"图片 AI 调用失败: {e}")
        return "收到，稍后回复你。"


# ── 消息处理主逻辑 ────────────────────────────────────────────────────────────
def handle_message(data: lark.im.v1.P2ImMessageReceiveV1):
    """核心处理：提取文本/图片 → AI 生成回复 → 发送"""
    try:
        message = data.event.message
        sender = data.event.sender

        # 忽略机器人自身发送的消息，避免循环回复
        if sender.sender_type == "app":
            logger.info("忽略机器人自身消息")
            return

        sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"

        # ── 图片消息（纯图片 or 富文本 post 里包含图片）────────────────────────
        if message.message_type in ("image", "post"):
            content = json.loads(message.content)

            # 纯图片消息
            if message.message_type == "image":
                image_keys = [content.get("image_key", "")]
                text = ""
            else:
                # post 富文本：遍历所有 block 提取 image_key 和文本
                image_keys = []
                text_parts = []
                for block in content.get("content", []):
                    for elem in block:
                        if elem.get("tag") == "img":
                            image_keys.append(elem.get("image_key", ""))
                        elif elem.get("tag") in ("text", "a"):
                            text_parts.append(elem.get("text", ""))
                text = re.sub(r"<at[^>]*>[^<]*</at>", "", " ".join(text_parts)).strip()

            image_keys = [k for k in image_keys if k]
            if not image_keys:
                # post 里没有图片，当普通文本处理
                if text:
                    logger.info(f"收到 post 文本消息 [{message.message_id}] 来自 {sender_id}: {text[:80]}")
                    reply = generate_reply(text)
                    send_text_message(chat_id=message.chat_id, text=reply)
                return

            logger.info(f"收到图片消息 [{message.message_id}] 来自 {sender_id}，图片数: {len(image_keys)}")
            image_b64 = download_image(message.message_id, image_keys[0])
            if image_b64:
                reply = generate_reply_with_image(image_b64, text)
                send_text_message(chat_id=message.chat_id, text=reply)
                # 反馈检测：用视觉分析结果判断是否为反馈，是则带图写入 Bitable
                feedback_text = f"{text}\n[图片内容：{reply}]" if text else f"[用户发送截图，图片内容：{reply}]"
                def _record_image(ft=feedback_text, ib=__import__('base64').b64decode(image_b64)):
                    category, summary = ai_detect_and_classify(ft)
                    if category:
                        save_feedback(feishu_client, sender_id, summary, message.chat_id, category, image_bytes=ib)
                threading.Thread(target=_record_image, daemon=True).start()
            else:
                send_text_message(chat_id=message.chat_id, text="图片下载失败，请重试。")
            return

        # ── 非文本且非图片，跳过 ──────────────────────────────────────────────
        if message.message_type != "text":
            logger.info(f"跳过不支持的消息类型: {message.message_type}")
            return

        # 解析消息文本，去掉 @mention 标记（格式：<at user_id="xxx">名字</at>）
        raw_text = json.loads(message.content).get("text", "").strip()
        text = re.sub(r"<at[^>]*>[^<]*</at>", "", raw_text).strip()
        was_mentioned = "<at" in raw_text  # 消息里有 @某人（含 @bot）

        logger.info(f"收到消息 [{message.message_id}] 来自 {sender_id}: {text[:80]}")

        # ── 过滤：@bot 直接回复；否则 AI 判断是否产品相关 ──────────────────
        if not was_mentioned and not should_reply(text):
            logger.info("消息与产品无关，跳过回复")
            return

        # ── AI 生成回复并发送 ─────────────────────────────────────────────────
        reply = generate_reply(text)
        send_text_message(chat_id=message.chat_id, text=reply)

        # ── 反馈检测：AI 判断是否为反馈，是则异步写入多维表格 ────────────────
        def _record():
            category, summary = ai_detect_and_classify(text)
            if category:
                save_feedback(feishu_client, sender_id, summary, message.chat_id, category)
        threading.Thread(target=_record, daemon=True).start()

    except Exception as e:
        logger.error(f"处理消息时发生未预期错误: {e}", exc_info=True)


# ── 飞书 SDK 事件回调（注册到 EventDispatcher）────────────────────────────────
def on_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    """
    SDK 在收到 im.message.receive_v1 事件时调用此函数
    SDK 要求 3 秒内返回，所以用子线程异步处理实际业务
    """
    event_id = data.header.event_id if data.header else ""

    # 去重：飞书可能对同一事件重复推送
    if event_id and _is_duplicate(event_id):
        logger.info(f"重复事件 {event_id}，跳过")
        return

    threading.Thread(target=handle_message, args=(data,), daemon=True).start()


# ── 程序入口 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 配置检查
    try:
        Config.validate()
        logger.info("配置校验通过")
    except EnvironmentError as e:
        logger.warning(f"配置不完整: {e}，部分功能可能无法使用")

    # 注册事件处理器
    # builder 的两个参数（verify_token, encrypt_key）长连接模式下必须填空字符串
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message_receive)
        .build()
    )

    # 启动长连接 WebSocket 客户端，阻塞主线程
    logger.info("正在连接飞书长连接服务（WebSocket）...")
    ws_client = lark.ws.Client(
        Config.FEISHU_APP_ID,
        Config.FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    ws_client.start()
