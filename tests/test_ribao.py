from datetime import datetime
import hashlib
import hmac
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import ribao
import grounded
from article_reader import article_text


DAY = "2026-10-30"
NOW = datetime(2026, 10, 31, 8, 30, tzinfo=ribao.SHANGHAI)
KEYS = {"DASHSCOPE_API_KEY": "test-key", "FEISHU_WEBHOOK_URL":
        "https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000000"}


def item(index=1, **overrides):
    return dict(title=f"事件 {index}", summary="有来源的摘要", why="判断：值得关注",
                source="发布机构", url=f"https://example.com/news/{index}",
                published_at=DAY, event_key=f"event-{index}", kind="news", score=90,
                details="", deadline="", date_verified=True, **{}) | overrides


def response(items=None, sources=None):
    items = items if items is not None else [item()]
    sources = sources if sources is not None else [{"url": value["url"]} for value in items]
    return {"output": {"choices": [{"message": {"content": json.dumps({"items": items})},
                                   "finish_reason": "stop"}],
                       "search_info": {"search_results": sources}}, "usage": {"total_tokens": 100}}


def report():
    return {"date": DAY, "sections": [
        {"id": sid, "title": sid, "items": [item(index)], "status": "complete"}
        for index, sid in enumerate(ribao.SECTIONS)]}


class ValidationTests(unittest.TestCase):
    def test_source_and_publication_day_are_required(self):
        with self.assertRaises(ribao.BriefError):
            ribao.validate_item(item(), DAY, {"https://other.example/news"})
        with self.assertRaises(ribao.BriefError):
            ribao.validate_item(item(published_at="2026-09-29"), DAY, {item()["url"]})

    def test_utc_publication_converts_to_beijing(self):
        self.assertEqual(ribao.iso_day("2026-10-29T17:30:00Z"), DAY)

    @patch("ribao.now", return_value=NOW)
    def test_expired_procurement_is_rejected(self, _):
        with self.assertRaises(ribao.BriefError):
            ribao.validate_item(item(kind="procurement", deadline="2026-10-31T08:00:00+08:00"), DAY, {item()["url"]})
        self.assertTrue(ribao.validate_item(item(kind="rfq", deadline="2026-10-31"), DAY, {item()["url"]}))

    def test_publication_metadata_not_any_date_or_modification(self):
        document = '<meta content="2026-10-30T20:00:00+08:00" property="article:published_time">'
        self.assertEqual(ribao.page_publication_dates(document), {DAY})
        self.assertEqual(ribao.page_publication_dates('"dateModified":"2026-10-30"'), set())
        self.assertEqual(ribao.page_publication_dates('页面底部 2026-10-30'), set())
        self.assertEqual(ribao.page_publication_dates('发布时间：2026年10月30日'), {DAY})
        self.assertEqual(ribao.page_publication_dates('"datePublished": "2026-10-30"'), {DAY})

    def test_no_sources_is_failure_even_when_model_says_empty(self):
        with self.assertRaises(ribao.BriefError):
            ribao.parse_search(response([], []))
        self.assertEqual(ribao.parse_search(response([], [{"url": "https://example.com"}]))[0], [])

    def test_truncated_generation_is_rejected(self):
        value = response()
        value["output"]["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(ribao.BriefError):
            ribao.parse_search(value)

    def test_tracking_parameters_do_not_hide_duplicates(self):
        self.assertEqual(ribao.canonical_url("https://example.com/a?id=1&utm_source=x#x"),
                         ribao.canonical_url("https://example.com/a?id=1"))

    def test_unverified_report_cannot_be_published(self):
        value = report()
        value["sections"][0]["items"][0].pop("date_verified")
        with self.assertRaises(ribao.BriefError):
            ribao.validate_report(value)

    def test_failure_is_not_rendered_as_no_news(self):
        section = dict(id="ai_tech", title="AI", items=[], status="unavailable")
        self.assertTrue(ribao.section_text(section).startswith("本栏暂时获取失败"))
        section["status"] = "complete"
        self.assertEqual(ribao.section_text(section), "暂无")

    def test_card_types_and_mentions(self):
        value = report()
        value["sections"][0]["items"][0].update(title="<at user_id=all>消息</at>", kind="supply")
        rendered = json.dumps(ribao.cards(value), ensure_ascii=False)
        self.assertIn("供应信息", rendered)
        self.assertNotIn("<at", rendered)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        test_root = (Path(__file__).resolve().parents[1] / "data" / "test-tmp").resolve()
        test_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temporary.cleanup)
        self.root_patch = patch("ribao.ROOT", Path(self.temporary.name))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.time_patch = patch("ribao.now", return_value=NOW)
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.config = {"model": "qwen-plus", "region": "cn-beijing", "workspace_id": "ws-test",
                       "search_strategy": "max", "max_tokens": 5000, "timeout_seconds": 180,
                       "sections": [dict(id=sid, title=sid, queries=["topic"]) for sid in ribao.SECTIONS]}

    def test_cli_handles_grounded_configuration_failure_without_traceback(self):
        source_root = Path(__file__).resolve().parents[1]
        for name in ("ribao.py", "grounded.py", "article_reader.py", "story_history.py", "github_hot.py"):
            (ribao.ROOT / name).write_text((source_root / name).read_text(encoding="utf-8"), encoding="utf-8")
        ribao.write_json(ribao.ROOT / "settings.json", self.config)
        environment = dict(os.environ, PYTHONUTF8="1")
        for name in ("DASHSCOPE_API_KEY", "FEISHU_WEBHOOK_URL", "FEISHU_SIGN_SECRET"):
            environment.pop(name, None)
        result = subprocess.run([sys.executable, str(ribao.ROOT / "ribao.py"), "run", "--preview-only"],
                                capture_output=True, text=True, encoding="utf-8", env=environment)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

    @patch("grounded.fetch_source")
    @patch("ribao.post_json")
    def test_pipeline_caps_ten_and_deduplicates_across_sections(self, post, fetch):
        # Repeated event in a second URL and repeated content across all sections.
        values = [item(i, score=100-i) for i in range(12)] + [item(99, event_key="event-0")]
        quote = "这是原始文章中可以逐字核对的新闻证据。"
        fetch.side_effect = lambda source, target, folder: dict(url=source["url"], title="来源文章", source="发布机构",
            text=quote * 5, published_at=DAY, error="")
        def api_reply(url, payload, headers, timeout):
            if payload["parameters"]["enable_search"]:
                return response(values)
            return {"output": {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"items": [
                dict(value, source_id=f"s{i + 1}", evidence_quote=quote) for i, value in enumerate(values)]})}}]}}
        post.side_effect = api_reply
        result = ribao.generate(self.config, KEYS, DAY)
        self.assertEqual([len(s["items"]) for s in result["sections"]], [10, 2, 0, 0])
        ribao.preview(result)
        self.assertTrue((ribao.ROOT / "data" / DAY / "cards.json").exists())
        request = post.call_args_list[0].args[1]
        self.assertTrue(request["parameters"]["enable_search"])
        self.assertTrue(request["parameters"]["search_options"]["forced_search"])
        self.assertIn("ws-test.cn-beijing.maas.aliyuncs.com", post.call_args.args[0])

    @patch("grounded.fetch_source", return_value=dict(url="https://example.com", source="发布机构", title="来源文章",
        text="这是日期无法核实的文章正文。" * 5, published_at="", error="原文发布日期无法确认"))
    @patch("ribao.post_json", return_value=response())
    def test_unverified_page_date_never_enters_brief(self, post, fetch):
        result = ribao.generate(self.config, KEYS, DAY)
        self.assertTrue(all(not s["items"] for s in result["sections"]))
        self.assertEqual(result["sections"][0]["yesterday_source_count"], 0)
        self.assertEqual(post.call_count, len(ribao.SECTIONS))  # No editorial call without dated sources.

    @patch("ribao.post_json", side_effect=ribao.BriefError("API故障"))
    def test_api_failure_remains_visible(self, post):
        result = ribao.generate(self.config, KEYS, DAY)
        self.assertTrue(all(s["status"] == "unavailable" for s in result["sections"]))

    @patch("ribao.time.sleep")
    @patch("ribao.post_json", return_value={"code": 0})
    def test_delivering_same_report_twice_sends_once(self, post, sleep):
        ribao.deliver(report(), KEYS)
        ribao.deliver(report(), KEYS)
        self.assertEqual(post.call_count, len(ribao.SECTIONS))

    @patch("ribao.time.sleep")
    @patch("ribao.post_json", return_value={"code": 0})
    def test_revision_can_follow_original_without_altering_original_receipt(self, post, sleep):
        original = report()
        ribao.deliver(original, KEYS)
        receipt = next((ribao.ROOT / "data" / DAY).glob("delivery-*.json"))
        before = receipt.read_bytes()
        corrected = report() | {"pipeline_version": 2}
        corrected["sections"][0]["items"][0]["summary"] = "修正后的有来源摘要"
        first = ribao.resend_review(corrected, KEYS)
        second = ribao.resend_review(corrected, KEYS)
        self.assertEqual(first, second)
        self.assertEqual(post.call_count, len(ribao.SECTIONS) * 2)
        self.assertEqual(receipt.read_bytes(), before)
        header = post.call_args_list[len(ribao.SECTIONS)].args[1]["card"]["header"]["title"]["content"]
        self.assertIn("【修正版】", header)
        self.assertEqual(len(list((ribao.ROOT / "data" / DAY).glob("delivery-*.json"))), 2)

    @patch("ribao.post_json", side_effect=ribao.BriefError("网络超时"))
    def test_uncertain_revision_is_not_blindly_repeated(self, post):
        corrected = report() | {"pipeline_version": 2}
        with self.assertRaises(ribao.BriefError):
            ribao.resend_review(corrected, KEYS)
        with self.assertRaisesRegex(ribao.BriefError, "结果不确定"):
            ribao.resend_review(corrected, KEYS)
        self.assertEqual(post.call_count, 1)

    @patch("ribao.time.sleep")
    @patch("ribao.post_json", return_value={"code": 0})
    def test_github_only_correction_does_not_repeat_other_cards(self, post, sleep):
        corrected = report() | {"pipeline_version": 3}
        first = ribao.resend_review(corrected, KEYS, sections=["github_hot"])
        second = ribao.resend_review(corrected, KEYS, sections=["github_hot"])
        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)
        self.assertIn("github_hot", post.call_args.args[1]["card"]["header"]["title"]["content"])
        receipt = next((ribao.ROOT / "data" / DAY).glob("delivery-*-revision-*.json"))
        state = ribao.read_json(receipt)
        self.assertEqual(state["parts"], {"4": "sent"})
        self.assertEqual(list(state["items_by_part"]), ["4"])
        self.assertEqual(state["items_by_part"]["4"], corrected["sections"][3]["items"])

    @patch("ribao.post_json", side_effect=ribao.BriefError("网络超时"))
    def test_selected_correction_keeps_original_part_number_for_recovery(self, post):
        corrected = report() | {"pipeline_version": 3}
        with self.assertRaises(ribao.BriefError):
            ribao.resend_review(corrected, KEYS, sections=["github_hot"])
        with self.assertRaisesRegex(ribao.BriefError, "第 4 张卡片结果不确定"):
            ribao.resend_review(corrected, KEYS, sections=["github_hot"])
        self.assertEqual(post.call_count, 1)

    @patch("ribao.post_json")
    def test_revision_rejects_old_or_unrebuilt_reports(self, post):
        for corrected in (report(), report() | {"pipeline_version": 2, "date": "2026-10-29"}):
            with self.assertRaises(ribao.BriefError):
                ribao.resend_review(corrected, KEYS)
        post.assert_not_called()

    @patch("ribao.time.sleep")
    @patch("ribao.post_json", side_effect=[{"code": 0}, {"code": 19024}, {"code": 0}, {"code": 0}, {"code": 0}])
    def test_explicit_rejection_resumes_from_failed_part(self, post, sleep):
        with self.assertRaises(ribao.BriefError):
            ribao.deliver(report(), KEYS)
        ribao.deliver(report(), KEYS)
        self.assertEqual(post.call_count, len(ribao.SECTIONS) + 1)

    @patch("ribao.post_json", side_effect=ribao.BriefError("网络超时"))
    def test_timeout_blocks_automatic_duplicate(self, post):
        with self.assertRaises(ribao.BriefError):
            ribao.deliver(report(), KEYS)
        with self.assertRaisesRegex(ribao.BriefError, "结果不确定"):
            ribao.deliver(report(), KEYS)
        self.assertEqual(post.call_count, 1)

    @patch("ribao.post_json")
    def test_demo_and_stale_reports_never_sent(self, post):
        for value in (report() | {"demo": True}, report() | {"date": "2026-10-29"}):
            with self.assertRaises(ribao.BriefError):
                ribao.deliver(value, KEYS)
        post.assert_not_called()


class TransportTests(unittest.TestCase):
    @patch("ribao.time.time", return_value=1234567890)
    def test_feishu_signature_matches_official_algorithm(self, _):
        expected = base64.b64encode(hmac.new(b"1234567890\nsecret", b"", hashlib.sha256).digest()).decode()
        self.assertEqual(ribao.signed({}, "secret")["sign"], expected)

    @patch("ribao.urllib.request.build_opener")
    def test_transport_error_does_not_expose_webhook_or_key(self, opener):
        private_url = KEYS["FEISHU_WEBHOOK_URL"]
        opener.return_value.open.side_effect = urllib.error.HTTPError(private_url, 403, "test-key", {}, None)
        with self.assertRaises(ribao.BriefError) as caught:
            ribao.post_json(private_url, {})
        self.assertNotIn(private_url, str(caught.exception))
        self.assertNotIn("test-key", str(caught.exception))

    @patch("ribao.socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))])
    def test_page_verifier_rejects_private_network(self, _):
        with self.assertRaises(ribao.BriefError):
            ribao.public_url("https://example.com/article")


if __name__ == "__main__":
    unittest.main()
