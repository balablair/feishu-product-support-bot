"""
飞书云文档知识库加载 — 启动时拉取指定文档内容，合并到知识库
支持新版文档（docx）和旧版文档（doc），以及 Wiki Space 自动遍历
"""

import logging
import lark_oapi as lark
from lark_oapi.api.docx.v1 import RawContentDocumentRequest
from lark_oapi.api.wiki.v2 import GetNodeSpaceRequest, ListSpaceNodeRequest

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


def _resolve_space_id(client: lark.Client, wiki_token: str) -> str:
    """通过 Wiki 页面 token 获取所属 space_id"""
    try:
        req = GetNodeSpaceRequest.builder().token(wiki_token).build()
        resp = client.wiki.v2.space.get_node(req)
        if resp.success() and resp.data and resp.data.node:
            return resp.data.node.space_id or ""
        logger.error(f"获取 Wiki Space ID 失败: code={resp.code} msg={resp.msg}")
    except Exception as e:
        logger.error(f"获取 Wiki Space ID 异常: {e}")
    return ""


def _list_all_nodes(
    client: lark.Client, space_id: str, parent_token: str = ""
) -> list[dict]:
    """递归列出 Wiki Space 下所有文档节点（含子页面）"""
    nodes: list[dict] = []
    page_token = None

    while True:
        builder = ListSpaceNodeRequest.builder().space_id(space_id)
        if parent_token:
            builder = builder.parent_node_token(parent_token)
        if page_token:
            builder = builder.page_token(page_token)

        try:
            resp = client.wiki.v2.space_node.list(builder.build())
            if not resp.success():
                logger.error(f"列出 Wiki 节点失败: code={resp.code} msg={resp.msg}")
                break

            for item in resp.data.items or []:
                if item.obj_type in ("doc", "docx"):
                    nodes.append(
                        {"obj_token": item.obj_token, "title": item.title or item.obj_token}
                    )
                # 递归处理有子节点的节点（包括文件夹和有子页面的文档）
                if item.has_children:
                    nodes.extend(_list_all_nodes(client, space_id, item.node_token))

            if not resp.data.has_more:
                break
            page_token = resp.data.page_token
        except Exception as e:
            logger.error(f"列出 Wiki 节点异常: {e}")
            break

    return nodes


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


def load_feishu_wiki(client: lark.Client) -> str:
    """
    遍历 FEISHU_WIKI_TOKEN 所在的 Wiki Space，自动加载所有文档。

    FEISHU_WIKI_TOKEN 填 Wiki 任意页面的 token（从页面 URL 中获取），
    程序会自动解析所属 Space 并递归获取全部文档。
    """
    wiki_token = Config.FEISHU_WIKI_TOKEN
    if not wiki_token:
        return ""

    # 通过页面 token 获取 space_id
    space_id = _resolve_space_id(client, wiki_token)
    if not space_id:
        logger.error("无法解析 Wiki Space ID，跳过 Wiki 知识库加载")
        return ""

    logger.info(f"开始加载 Wiki Space: {space_id}")
    node_list = _list_all_nodes(client, space_id)
    if not node_list:
        logger.warning(f"Wiki Space {space_id} 无可访问文档")
        return ""

    parts = []
    for node in node_list:
        content = _fetch_one(client, node["obj_token"]).strip()
        if content:
            parts.append(f"=== Wiki:{node['title']} ===\n{content}")
            logger.info(f"Wiki 文档已加载: {node['title']}（{len(content)} 字符）")
        else:
            logger.warning(f"Wiki 文档内容为空，跳过: {node['title']}")

    logger.info(f"Wiki Space 加载完成，共 {len(parts)} 篇文档")
    return "\n\n".join(parts)
