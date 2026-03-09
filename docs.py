"""
飞书云文档知识库加载 — 启动时拉取指定文档内容，合并到知识库
支持新版文档（docx）和旧版文档（doc）
"""

import logging
import lark_oapi as lark
from lark_oapi.api.docx.v1 import RawContentDocumentRequest
from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest

from config import Config

logger = logging.getLogger(__name__)


def _resolve_wiki_token(client: lark.Client, wiki_token: str) -> str:
    """将 wiki token 解析为底层 docx token"""
    try:
        req = GetNodeSpaceRequest.builder().token(wiki_token).build()
        resp = client.wiki.v2.space.get_node(req)
        if resp.success() and resp.data and resp.data.node:
            return resp.data.node.obj_token or ""
        logger.error(f"Wiki token 解析失败: code={resp.code} msg={resp.msg}")
    except Exception as e:
        logger.error(f"Wiki token 解析异常: {e}")
    return ""


def _fetch_one(client: lark.Client, token: str) -> str:
    """拉取单个文档的纯文本内容，自动识别 wiki token"""
    # 先尝试直接当 docx 拉取，失败则尝试 wiki 解析
    try:
        req = RawContentDocumentRequest.builder().document_id(token).build()
        resp = client.docx.v1.document.raw_content(req)
        if resp.success():
            return resp.data.content or ""
        # 可能是 wiki token，尝试解析
        logger.info(f"直接拉取失败，尝试按 wiki token 解析: {token}")
        doc_token = _resolve_wiki_token(client, token)
        if doc_token:
            req2 = RawContentDocumentRequest.builder().document_id(doc_token).build()
            resp2 = client.docx.v1.document.raw_content(req2)
            if resp2.success():
                return resp2.data.content or ""
            logger.error(f"文档 {doc_token} 拉取失败: code={resp2.code} msg={resp2.msg}")
        else:
            logger.error(f"文档 {token} 拉取失败: code={resp.code} msg={resp.msg}")
    except Exception as e:
        logger.error(f"文档 {token} 拉取异常: {e}")
    return ""


def load_feishu_docs(client: lark.Client) -> str:
    """
    拉取 FEISHU_DOC_TOKENS 中所有文档内容，合并为一段文本
    格式与本地 knowledge/ 保持一致
    """
    tokens = [t.strip() for t in Config.FEISHU_DOC_TOKENS.split(",") if t.strip()]
    if not tokens:
        return ""

    parts = []
    for token in tokens:
        content = _fetch_one(client, token).strip()
        if content:
            parts.append(f"=== 飞书文档:{token} ===\n{content}")
            logger.info(f"云文档已加载: {token}（{len(content)} 字符）")
        else:
            logger.warning(f"云文档内容为空，跳过: {token}")

    return "\n\n".join(parts)
