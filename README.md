# 飞书智能客服机器人

面向产品团队的飞书群智能助手，开箱即用。无需公网 IP，5 分钟完成部署。

**核心功能：**
- 知识库问答：基于你的产品文档自动回答用户问题
- 用户反馈收集：AI 自动识别并分类 Bug / 功能建议，写入飞书多维表格
- 图片理解：用户发送截图时自动分析报错内容
- 智能过滤：只回复与产品相关的消息，不打扰群内日常聊天

---

## 快速开始

### 方式一：配置向导（推荐）

安装依赖后运行向导，AI 会帮你完成所有配置，包括自动生成机器人人格文件：

```bash
pip install -r requirements.txt
python setup.py
```

向导会引导你完成：飞书凭证配置 → AI 模型选择 → 与 AI 对话生成 SOUL.md → 可选功能开关 → 生成 `.env`

---

### 方式二：手动配置

### 1. 准备飞书应用

1. 前往 [飞书开放平台](https://open.feishu.cn/app) 创建企业自建应用
2. 在「权限管理」中开通以下权限：
   - `im:message`（接收和发送消息）
   - `im:message.group_at_msg`（接收群 @ 消息）
   - `contact:user.base:readonly`（读取用户信息，用于反馈记录）
   - `bitable:app`（写入多维表格，可选）
   - `docx:document:readonly`（读取云文档，可选）
   - `wiki:wiki:readonly`（读取 Wiki Space，可选）
3. 在「事件与回调 - 长连接」中开启长连接模式
4. 将应用发布并邀请加入目标群组

### 2. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的配置：

```env
# 必填
FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PRODUCT_NAME=你的产品名称
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> **支持任何 OpenAI 兼容 API**：DeepSeek、OpenAI、Moonshot、智谱、阿里百炼等均可，修改 `OPENAI_API_URL` 和 `OPENAI_MODEL` 即可切换。

### 4. 配置 bot 人格（必做）

编辑 `SOUL.md`，将 `[产品名称]` 替换为你的产品名，并根据产品特性修改能力边界描述。

### 5. 添加知识库（推荐）

将产品文档复制到 `knowledge/` 目录，支持 `.md` `.txt` `.pdf` `.docx` `.pptx`。

**方式 A：指定单个文档** — 在 `.env` 中填写文档 token，bot 启动时自动拉取：

```env
FEISHU_DOC_TOKENS=文档token1,文档token2
```

**方式 B：接入整个 Wiki Space（推荐）** — 填写 Wiki 任意页面 token，bot 自动遍历整个 Space 的所有文档：

```env
FEISHU_WIKI_TOKEN=YLaCwu5OgiF1UGkEF2gcQTKkn8b   # 从 Wiki 页面 URL 末尾获取
```

> 使用 Wiki Space 需额外两步：① 在飞书开放平台开通 `wiki:wiki:readonly` 权限；② 在 Wiki 设置 → 成员管理中将机器人添加为成员。

知识库更新后，在飞书发送 `/reload`（管理员）即可热更新，无需重启。

### 6. 启动

```bash
python app.py
```

---

## Docker 部署

```bash
# 确保 .env 文件已配置好
docker compose up -d
```

---

## 可选功能配置

### 用户反馈自动收集

**只需创建一张空表格**，bot 首次启动时会自动创建所有字段（反馈内容、用户、问题分类、状态、反馈日期、回复内容、负责人、附件）。

1. 在飞书中创建一个多维表格，新建一张空白数据表
2. 从 URL 中获取 `app_token`（`/base/` 后面的部分）和 `table_id`（`/table/` 后面的部分）
3. 在 `.env` 中配置：

```env
BITABLE_APP_TOKEN=从多维表格 URL 中获取
BITABLE_TABLE_ID=从多维表格 URL 中获取
```

### 图片理解（截图分析）

配置阿里云百炼的 API Key（使用 Qwen-VL 模型）：

```env
VISION_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 项目结构

```
feishu-product-support-bot/
├── app.py              # 主程序：飞书长连接、消息处理
├── config.py           # 配置加载（从环境变量读取）
├── feedback.py         # 反馈识别与多维表格写入
├── docs.py             # 飞书云文档知识库拉取
├── SOUL.md             # Bot 人格定义（你来填写）
├── knowledge/          # 本地知识库文件目录
├── .env.example        # 环境变量模板
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## 工作原理

```
用户在飞书群发消息
       ↓
飞书 WebSocket 长连接推送事件（无需公网 IP）
       ↓
AI 判断是否与产品相关（基于 PRODUCT_NAME）
       ↓（相关）
合并知识库（本地文件 + 飞书云文档 + Wiki Space）+ SOUL.md 构建 system prompt
       ↓
调用 AI 生成回复 → 发送到群
       ↓（异步）
AI 判断是否为用户反馈 → 写入飞书多维表格
```

---

## License

MIT
