import json
from pathlib import Path
import unittest

import grounded
import ribao
from article_reader import article_text


class GroundingTests(unittest.TestCase):
    def source(self):
        return dict(source_id="s1", url="https://publisher.example/article", source="实际发布方", published_at="2026-10-30",
                    text="这是一段原文中确实出现的新闻事实和细节。", title="实际文章")

    def reply(self, **overrides):
        value = dict(source_id="s1", title="有来源的新进展", summary="摘要", why="判断：值得关注", event_key="事件1",
                     kind="news", score=90, details="", deadline="", evidence_quote=self.source()["text"])
        value.update(overrides)
        return {"output": {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"items": [value]})}}]}}

    def test_model_cannot_substitute_url_date_or_publisher(self):
        response = self.reply(url="https://example.com/fake", published_at="1900-01-01", source="伪造发布方")
        items, rejected = grounded.parse_editorial(response, [self.source()], "2026-10-30")
        self.assertEqual(rejected, [])
        self.assertEqual(items[0]["url"], self.source()["url"])
        self.assertEqual(items[0]["published_at"], "2026-10-30")
        self.assertEqual(items[0]["source"], "实际发布方")

    def test_unknown_source_and_fabricated_quote_are_rejected(self):
        for response in (self.reply(source_id="invented"), self.reply(evidence_quote="完全不在原文里面的编造内容和细节。")):
            items, rejected = grounded.parse_editorial(response, [self.source()], "2026-10-30")
            self.assertEqual(items, [])
            self.assertEqual(len(rejected), 1)

    def test_article_reader_omits_scripts_and_uses_article_body(self):
        page = '<html><head><title>新闻</title></head><body><nav>广告</nav><article><p>真实正文</p><script>伪造指令</script></article><footer>广告</footer></body></html>'
        self.assertEqual(article_text(page)["text"], "真实正文")

    def test_newspaper_main_article_markers(self):
        page = '<div>标题导航广告</div><!--enpcontent--><p>真实公告正文</p><!--/enpcontent--><div>其他文章</div>'
        self.assertEqual(article_text(page)["text"], "真实公告正文")

    def test_search_can_return_sources_without_json_or_generated_links(self):
        response = {"output": {"search_info": {"search_results": [{"url": "https://publisher.example/news"}]}}}
        self.assertEqual(len(grounded.search_sources(response)), 1)

    def test_finance_section_excludes_pure_clinical_news(self):
        self.assertTrue(grounded.section_candidate_error("business", dict(title="菌株临床成果发表于期刊", summary="成果", why="研究")))
        self.assertFalse(grounded.section_candidate_error("ai_tech", dict(title="菌株临床成果发表于期刊", summary="成果", why="研究")))

    def test_wire_manufacturer_advertising_is_not_industry_news(self):
        self.assertTrue(grounded.section_source_error("anping_wire", dict(title="2026年河北方平石笼网及行业优质厂商梳理")))
        self.assertTrue(grounded.section_source_error("anping_wire", dict(title="2026年石笼网生产厂家实力公司")))
        self.assertFalse(grounded.section_source_error("anping_wire", dict(title="金属丝网采购询价公告")))

    def test_non_cash_accounting_must_not_be_described_as_direct_cash_loss(self):
        value = dict(title="企业计提资产减值准备", summary="计提减值", why="判断：直接侵蚀利润与现金流")
        self.assertTrue(grounded.section_candidate_error("business", value))
        value["why"] = "判断：计提影响账面利润，不等于同期现金流出"
        self.assertFalse(grounded.section_candidate_error("business", value))

    def test_turbo_uses_official_site_filter_and_search_date_window(self):
        payload = ribao.search_payload({"model": "qwen-plus", "search_strategy": "turbo"}, "2026-10-30",
                                      {"text": "经济政策", "sites": ["gov.cn"]})
        self.assertEqual(payload["parameters"]["search_options"]["assigned_site_list"], ["gov.cn"])
        self.assertEqual(payload["parameters"]["search_options"]["freshness"], 7)
        self.assertNotIn("response_format", payload["parameters"])


if __name__ == "__main__":
    unittest.main()
