"""
用户反馈自动收集 — 检测到反馈消息后写入飞书多维表格
"""

import logging
import requests
from datetime import datetime

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import CreateAppTableRecordRequest, AppTableRecord
from lark_oapi.api.im.v1 import GetMessageRequest

from config import Config

logger = logging.getLogger(__name__)

_CATEGORIES = ["Bug报错", "功能建议", "使用问题", "其他"]

def _build_should_reply_prompt() -> str:
    product = Config.PRODUCT_NAME
    return f"""\
判断下面这条群消息是否值得机器人回复。只有以下情况需要回复：
- 关于 {product} 产品的使用问题、功能咨询、操作指导
- 用户反馈（Bug 报错、功能建议、使用问题）
- 任何与 {product} 产品相关的问题

以下情况不需要回复：
- 群内闲聊、打招呼、问候、表情包
- 与 {product} 完全无关的话题
- 用户之间的日常对话

只返回 YES 或 NO，不要任何其他内容。"""


def should_reply(text: str) -> bool:
    """用 AI 判断消息是否值得回复，失败时默认回复"""
    if not Config.OPENAI_API_KEY:
        return True
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
                    {"role": "system", "content": _build_should_reply_prompt()},
                    {"role": "user", "content": text},
                ],
                "temperature": 0,
                "max_tokens": 5,
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip().upper()
        return result == "YES"
    except Exception as e:
        logger.warning(f"should_reply 判断失败，默认回复: {e}")
        return True


_CLASSIFY_PROMPT = """\
你是一个用户反馈审核助手。判断下面的内容是否属于用户反馈（Bug 报错、功能建议、使用问题等）。

如果是用户反馈，用以下格式回复（两行）：
第一行：分类（四选一）：Bug报错、功能建议、使用问题、其他
第二行：用一句话概括这条反馈的核心问题（15字以内，简洁直接）

如果不是用户反馈，只返回：无"""


def ai_detect_and_classify(text: str) -> tuple[str, str] | tuple[None, None]:
    """
    用 AI 判断消息是否为用户反馈，返回 (分类, 一句话总结) 或 (None, None)。
    """
    if not Config.OPENAI_API_KEY:
        return None, None
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
                    {"role": "system", "content": _CLASSIFY_PROMPT},
                    {"role": "user", "content": text},
                ],
                "temperature": 0,
                "max_tokens": 60,
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        if result == "无":
            return None, None
        lines = result.splitlines()
        category = lines[0].strip() if lines else "其他"
        summary = lines[1].strip() if len(lines) > 1 else text[:50]
        return (category if category in _CATEGORIES else "其他"), summary
    except Exception as e:
        logger.warning(f"AI 反馈判断失败，跳过记录: {e}")
        return None, None


def upload_image_for_bitable(image_bytes: bytes, filename: str = "feedback.jpg") -> str | None:
    """上传图片到飞书云盘，返回 file_token 供 Bitable 附件字段使用"""
    try:
        token_resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": Config.FEISHU_APP_ID, "app_secret": Config.FEISHU_APP_SECRET},
            timeout=10,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["tenant_access_token"]

        resp = requests.post(
            "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {access_token}"},
            data={
                "file_name": filename,
                "parent_type": "bitable_file",
                "parent_node": Config.BITABLE_APP_TOKEN,
                "size": str(len(image_bytes)),
            },
            files={"file": (filename, image_bytes, "image/jpeg")},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 0:
            file_token = result["data"]["file_token"]
            logger.info(f"图片已上传到飞书云盘: {file_token}")
            return file_token
        logger.error(f"图片上传失败: {result}")
        return None
    except Exception as e:
        logger.error(f"图片上传异常: {e}")
        return None


def get_user_name(client: lark.Client, open_id: str) -> str:
    """通过 open_id 获取用户显示名，失败时返回 open_id"""
    try:
        from lark_oapi.api.contact.v3 import GetUserRequest
        req = (
            GetUserRequest.builder()
            .user_id_type("open_id")
            .user_id(open_id)
            .build()
        )
        resp = client.contact.v3.user.get(req)
        if resp.success() and resp.data and resp.data.user:
            return resp.data.user.name or open_id
    except Exception as e:
        logger.debug(f"获取用户名失败: {e}")
    return open_id


def save_feedback(
    client: lark.Client,
    open_id: str,
    text: str,
    chat_id: str,
    category: str = "其他",
    image_bytes: bytes | None = None,
) -> bool:
    """将反馈写入飞书多维表格，image_bytes 不为空时同时上传附件"""
    if not (Config.BITABLE_APP_TOKEN and Config.BITABLE_TABLE_ID):
        logger.warning("Bitable 未配置（BITABLE_APP_TOKEN / BITABLE_TABLE_ID），跳过记录")
        return False

    now_ms = int(datetime.now().timestamp() * 1000)

    fields = {
        "反馈内容": text,
        "用户": [{"id": open_id}],
        "问题分类": category,
        "状态": "待处理",
        "反馈日期": now_ms,
        "回复内容": "",
    }
    if Config.FEEDBACK_DEFAULT_ASSIGNEE:
        fields["负责人"] = [{"id": Config.FEEDBACK_DEFAULT_ASSIGNEE}]

    if image_bytes:
        file_token = upload_image_for_bitable(image_bytes)
        if file_token:
            fields["附件"] = [{"file_token": file_token}]

    try:
        req = (
            CreateAppTableRecordRequest.builder()
            .app_token(Config.BITABLE_APP_TOKEN)
            .table_id(Config.BITABLE_TABLE_ID)
            .request_body(AppTableRecord.builder().fields(fields).build())
            .build()
        )
        resp = client.bitable.v1.app_table_record.create(req)
        if resp.success():
            logger.info(f"反馈已写入 Bitable | 用户={open_id} | 分类={category}")
            return True
        logger.error(f"Bitable 写入失败: code={resp.code} msg={resp.msg}")
        return False
    except Exception as e:
        logger.error(f"Bitable 写入异常: {e}")
        return False
