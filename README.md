# 飞书产品支持机器人

让 AI 在飞书群里 7×24 小时替你回答用户问题、自动记录用户反馈。

**适合谁用：** 产品团队、运营团队，不需要技术背景，跟着步骤操作即可。

**能做什么：**
- 用户问产品怎么用 → AI 查阅你的文档，自动回复
- 用户报错或提建议 → 自动分类整理到飞书多维表格
- 用户发截图 → AI 读图分析报错内容
- 跟产品无关的闲聊 → 自动忽略，不打扰群内日常

---

## 开始之前，你需要准备

**1. Python 3.10 或更新版本**

打开终端（Mac 按 `⌘ + 空格` 搜索"终端"，Windows 搜索"cmd"），输入：

```
python --version
```

如果显示 `Python 3.10.x` 或更高就可以。没有的话去 [python.org](https://www.python.org/downloads/) 下载安装。

**2. 一个飞书自建应用**

前往 [飞书开放平台](https://open.feishu.cn/app) → 创建企业自建应用。

创建后需要开通权限（在应用的「权限管理」页面搜索并添加）：

| 权限名 | 用途 |
|--------|------|
| `im:message` | 收发消息（必须）|
| `im:message.group_at_msg` | 接收群消息（必须）|
| `contact:user.base:readonly` | 识别是哪个用户（必须）|
| `bitable:app` | 把反馈写入表格（可选）|
| `docx:document:readonly` | 读取飞书云文档（可选）|
| `wiki:wiki:readonly` | 读取 Wiki 知识库（可选）|

然后在应用的「事件与回调」→「长连接」中，**开启长连接模式**（这样机器人不需要服务器公网 IP）。

**3. 一个 AI API Key**

推荐使用 [DeepSeek](https://platform.deepseek.com/)，注册后充值几块钱即可，回答一万条消息大概花 1-2 元。OpenAI、Moonshot 等也都支持。

---

## 第一步：下载项目

```bash
git clone https://github.com/balablair/feishu-product-support-bot.git
cd feishu-product-support-bot
```

没有 git？也可以点页面右上角 **Code → Download ZIP**，解压后进入文件夹。

---

## 第二步：运行设置向导

在终端进入项目文件夹，运行：

```bash
pip install -r requirements.txt
python setup.py
```

> 第一行会自动下载程序需要的组件，等它跑完就行（大约 1-2 分钟）。

向导会一步步问你：
1. 飞书应用的 ID 和密钥（自动测试连通性）
2. 选择 AI 服务商，填入 API Key（自动测试）
3. 用 AI 生成机器人的「人格文件」——告诉它自己是谁、能回答什么问题
4. 开启你需要的功能（反馈收集、图片理解、Wiki 知识库等）

完成后会自动生成配置文件，直接进入第三步。

---

## 第三步：添加知识库

把你的产品文档放进 `knowledge/` 文件夹，支持这些格式：

`.pdf` `.docx` `.pptx` `.md` `.txt`

**或者直接连接飞书 Wiki：** 如果你在飞书 Wiki 里有产品文档，可以让机器人直接读取整个知识库——打开任意一篇 Wiki 文档，复制 URL 末尾的那串字母，填入 `.env` 文件中的 `FEISHU_WIKI_TOKEN`。

> 知识库有更新？在飞书群里发送 `/reload`，机器人会立刻重新读取，无需重启。（仅管理员可用）

---

## 第四步：启动机器人

```bash
python app.py
```

看到 `connected` 字样说明连接成功。把机器人邀请进飞书群，就可以开始使用了。

> **让机器人一直在线：** 关掉终端机器人就会停。如果需要 24 小时运行，请看下方「服务器部署」。

---

## 反馈收集表格配置

如果在向导中开启了「用户反馈收集」，机器人会把用户的 Bug 报告、功能建议自动整理进飞书多维表格。

**只需要创建一张空表格**，不用手动加任何列——机器人第一次启动时会自动建好所有字段。

操作步骤：
1. 在飞书中新建一个多维表格，里面创建一张空白数据表
2. 打开这张表，从浏览器 URL 里复制两段信息：
   - `/base/` 后面的一串字符 → 填入 `BITABLE_APP_TOKEN`
   - `/table/` 后面的一串字符 → 填入 `BITABLE_TABLE_ID`

---

## 服务器部署（让机器人 24 小时在线）

需要一台 Linux 服务器（阿里云、腾讯云等，最低配置即可），安装好 Docker 后运行：

```bash
docker compose up -d
```

机器人会在后台持续运行，服务器重启后自动恢复。

---

## 常见问题

**机器人没有回复？**
- 检查它有没有被邀请进群
- 检查飞书应用权限是否申请了 `im:message`
- 看终端是否有报错信息

**知识库没有生效？**
- 检查文档是否放在 `knowledge/` 文件夹内
- 在群里发送 `/reload` 重新加载

**想改机器人的回答风格？**
- 编辑 `SOUL.md` 文件，这是机器人的「人格设定」，用自然语言描述就行

---

## 给技术同学看的内容

<details>
<summary>项目结构</summary>

```
feishu-product-support-bot/
├── app.py          # 主程序：飞书长连接、消息处理、对话历史
├── config.py       # 配置加载（从环境变量读取）
├── feedback.py     # 反馈识别、分类、写入 Bitable
├── docs.py         # 飞书云文档 / Wiki Space 拉取
├── rag.py          # RAG 向量检索（Dashscope text-embedding-v3）
├── setup.py        # CLI 配置向导（含 AI 生成 SOUL.md）
├── SOUL.md         # Bot 人格定义
├── knowledge/      # 本地知识库文件目录
├── tests/          # 单元测试
├── Dockerfile
└── docker-compose.yml
```

</details>

<details>
<summary>工作原理</summary>

```
用户在飞书群发消息
       ↓
飞书 WebSocket 长连接推送事件（无需公网 IP）
       ↓
AI 判断是否与产品相关（基于 PRODUCT_NAME）
       ↓（相关）
RAG 检索知识库最相关片段 + SOUL.md 构建 prompt
       ↓
调用 AI 生成回复 → Thread 回复到群
       ↓（异步）
AI 判断是否为用户反馈 → 写入飞书多维表格
```

</details>

<details>
<summary>手动配置（不使用向导）</summary>

```bash
cp .env.example .env
# 编辑 .env，填入各项配置
python app.py
```

所有可配置项见 `.env.example`，每项都有注释说明。

</details>

---

## License

MIT
