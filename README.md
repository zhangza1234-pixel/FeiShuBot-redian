# 飞书每日热点日报

代码仓库：[zhangza1234-pixel/FeiShuBot-redian](https://github.com/zhangza1234-pixel/FeiShuBot-redian)。当前通过本机 Windows 定时任务运行，尚未配置云端执行。

每天北京时间 08:30 开始联网整理公开信息，完成后推送到自己的飞书群。四板块各精选最多 10 条：

1. 前沿 AI 与科技产品。
2. 财商、商业和经济：结合真实事件解释经营、现金流、成本、财务和市场变化。
3. 安平丝网：本地产业新闻、采购招标、求购、供应链和国内外贸易机会。
4. GitHub 热点：近期更新的高星开源项目，用中文说明用途、适合谁、一个实际使用场景，并保留累计星标、语言和仓库链接。

优先昨天，少于 10 条时补充截至昨日的最近 30 天消息，保留实际日期；仍不足则按实际条数展示，完全没有写“暂无”。每条末尾附原文或仓库链接；采购信息保留可核实的规格、地区和截止日期，已截止需求不推荐。群卡片不显示候选拒绝、跳过数量等技术说明，整栏获取失败仅显示简短提示。

同一天各栏按事件去重，并按目标群的实际投递记录排除最近 30 天发过的链接、同类标题和事件。GitHub 同一仓库近 30 天仅推荐一次；预览不占用发送历史，结果不明确的投递按可能已送达处理，避免自动重复。

## 运行方式

采用北京地域阿里云百炼 `qwen-plus` 原生 API，开启强制联网搜索和来源返回，由 Python 标准库程序生成并推送日报。Windows 任务计划程序每天 08:30 启动，运行不依赖 Codex。需要电脑开机、当前 Windows 用户登录且网络可用；08:30 是开始时间，检索完成后发送，并非精确到分钟送达。

先调用 8 次昨日主题检索，三个新闻板块各整理一次；不足时各追加一次月内检索及整理，新闻最多 17 次百炼调用。GitHub 单独使用至多 2 次公开搜索，读取项目 README 后追加一次批量中文用途整理，全量生成合计最多 18 次百炼调用。公开 README 优先从原始文件地址读取，失败时回退 GitHub API，无需另配 GitHub Key；每个候选最多两次读取。模型及联网服务按百炼实际规则计费，保存 usage 供核对，不循环重试。资料依据和异常恢复见 `docs/daily-run.md`。

检索与整理分开执行：先读取真实来源及原文，校验日期，再将正文和固定来源编号交给模型。链接、发布方和日期由程序绑定；模型需引用正文中真实出现的连续证据片段。主题检索按 settings.json 提示优先站点，本地排除百科、长期产品目录等低相关页面；默认使用实测能返回来源的 max 策略。

要求 Python 3.11+，无需安装第三方依赖。

```powershell
cd D:\Code\FeiShuBot\ribao
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\Code\FeiShuBot\ribao\scripts\setup.ps1"
```

命令中的执行策略仅用于新启动的 PowerShell 进程，不修改系统或用户的永久策略；定时任务启动参数也采用相同设置。如果只想检查入口是否能启动，在命令末尾追加 `-CheckOnly`，不会读取凭据、调用模型或发消息。

配置脚本会依次询问百炼 Workspace ID、北京地域 API Key、飞书 Webhook 和可选签名密钥；凭据隐藏输入，保存到被 Git 忽略的 `.local/secrets.json`。Workspace ID 是非敏感路由信息，写入 settings.json。也支持 `DASHSCOPE_API_KEY`、`FEISHU_WEBHOOK_URL`、`FEISHU_SIGN_SECRET` 环境变量。

随后实际调用百炼生成昨日预览、发送飞书连接测试和首次正式日报，全部成功后安装或启用每日任务。某一步失败即停止，按提示处理后重跑。只想保存配置时可单独运行 `python ribao.py configure`；此命令不会调用 API 或发消息。

在飞书目标群进入“设置 → 群机器人 → 添加机器人 → 自定义机器人”，复制 Webhook；推荐开启签名校验并复制密钥。如果开启关键词安全设置，请包含“日报”。不要把凭据发到聊天。

```powershell
# 创建本地示例预览，不发送消息（文件明确标注为示例）
python ribao.py demo
# 实际调用百炼，但不向群发送
python ribao.py run --preview-only
# 复用当日已保存搜索结果重建独立预览，保留已投递的报告和回执
python ribao.py rebuild-preview
# 补发已生成的修正版（卡片标注“修正版”，不调用模型）
python ribao.py resend
# 只补发 GitHub 栏的修正版，其他三栏不重复发送
python ribao.py resend --input data/2026-10-30/github-usage-review/report.json --section github_hot
# 检查实际检索产物并生成 Markdown 与飞书卡片
python ribao.py preview --input data/2026-10-30/report.json
# 用户已授权每天推送；命令会校验日期、阻止重复发送
python ribao.py send --input data/2026-10-30/report.json
python -m unittest discover -s tests -v
```

send 默认只允许发送“今天的昨天”这一期正式日报，期内条目可以来自最近 30 天，支持失败后从未发送卡片继续。超时或响应不明确时记录 uncertain，人工检查群后再使用 recover 命令处理；不会盲目重发。

resend 默认读取 data/昨日日期/review/report.json，以内容生成修正版编号和独立回执，保留原日报回执。同一修正版重复执行会跳过已发卡片。修正版发送结果不明确时，使用 `recover --revision 修正版编号 --part 1 --resolution sent`（或 retry），随后再运行 resend。

## 资料入口

- `AGENTS.md`：工作规则、推送授权和凭据边界。
- `STATUS.md`：当前验证结果和待办。
- `docs/daily-run.md`：每日检索和投递流程。
- `docs/report-format.md`：报告 JSON 字段。
- `tasks/`：实施与交接资料；`archive/`：历史材料。
- `.local/`：本地凭据；`data/YYYY-MM-DD/`：原始报告、预览和发送回执，均不入库。

## 已知边界

公开网页并非完整的订单市场。来源访问失败、日期不明、登录后内容和无法核实的线索不计入有效条目；供应广告不会当作求购。外贸机会需有明确发布方、具体丝网相关性和可核实日期。只读公开资料，不代为联系和交易。程序校验来源和可识别的网页发布日期，不能取代全文事实核查或采购方资质调查。

GitHub 栏使用官方仓库搜索，优先最近昨日有更新且累计星标不少于 100 的项目，按累计星标排序；不足时扩展至近 30 天。更新日期是代码推送时间，星标是累计值，不表示当日增长或 GitHub Trending 榜单。标题改写及多站转载的语义去重仍可能存在遗漏。

每日任务名为 `Ribao-Feishu-Daily-0830`，电脑关机或用户未登录时不会运行；不会补发关机期间的旧日报。结果见 Windows 任务计划程序和 `data/logs/`。本版没有独立告警渠道。任务可用 `Disable-ScheduledTask -TaskName Ribao-Feishu-Daily-0830` 暂停，通过配置脚本重新启用。

协议依据：[百炼联网搜索](https://help.aliyun.com/zh/model-studio/web-search)、[百炼结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)、[飞书群自定义机器人](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot?lang=zh-CN)。
