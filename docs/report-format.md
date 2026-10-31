# 报告结构

`report.json` 由程序生成，人工修改后 preview/send 仍会检查结构和日期。date 是本期对应的昨日日期，issue_date 是展示的今日日期；条目的实际时间允许位于 date 向前共 30 天内。

```json
{
  "pipeline_version": 3,
  "date": "2026-10-30",
  "issue_date": "2026-10-31",
  "window_start": "2026-10-01",
  "generated_at": "2026-10-31T08:30:00+08:00",
  "sections": [
    {
      "id": "ai_tech",
      "title": "前沿 AI 与科技产品",
      "status": "complete",
      "items": [],
      "errors": [],
      "rejected_count": 0,
      "rejected_reasons": []
    }
  ]
}
```

v3 必须按顺序包含 ai_tech、business、anping_wire、github_hot 四栏。为回读原投递记录，v1/v2 的三栏报告仍有效。status 为 complete、partial 或 unavailable；完整空结果显示“暂无”，故障空栏显示简短失败提示。有内容时仅展示条目，过滤原因与内部统计保存到 JSON。

条目字段由 grounded.py 的 EDITOR、parse_editorial 及 ribao.py 的 validate_item 定义：标题、摘要、关注理由、来源链接、发布时间、事件标识、类型、编辑优先级、可选截止时间和详情。新闻还含 source_id 与 evidence_quote。程序核对原文日期后写入 date_verified=true，并依据 source_id 绑定真实链接、发布方和日期。GitHub 的 kind=repository，published_at 表示 API 返回的 pushed_at，stars 为累计星标；github_explained=true 表示已生成中文用途（summary）、受众（audience）和场景（use_case），原始说明保存在 repository_description。用途证据由模型选择 source_id/evidence_id，再由程序绑定 evidence_quote；说明失败不发布英文回退项。模型生成的链接/日期不会被采用。搜索来源、正文缓存、整理原始响应均单独保留以供回查。

每板块最多 10 条。分数是模型编辑优先级，不是社交平台真实阅读量或热度。demo=true 的报告仅可预览，不能投递。

回执按 Webhook 指纹隔离，parts 保存每张卡片的 sent/failed/uncertain 状态，items_by_part 保存实际提交的条目快照。近 30 天 sent/uncertain 条目用于跨天去重。旧回执无快照时读取对应原报告或 revisions/编号/report.json，不能用可变的 review 预览代替。

delivery_sections 是可选的非空板块 ID 列表，表示修正版只补发这些板块；完整报告仍保留全部四栏，回执 parts 使用原卡片编号，不因筛选而重新编号。
