from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import github_hot
import grounded
import ribao
from story_history import StoryHistory, in_window, load_history, month_start


DAY = "2026-10-30"
NOW = datetime(2026, 10, 31, 8, 30, tzinfo=ribao.SHANGHAI)
KEYS = {"DASHSCOPE_API_KEY": "test-key", "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/test-destination"}


def item(number, published=DAY, **changes):
    return dict(title=f"项目{number}发布具体新版本", summary="可以回查的事件摘要", why="判断：值得关注",
                source="发布机构", url=f"https://example.com/news/{number}", published_at=published,
                event_key=f"project-{number}-release", kind="news", score=90, details="", deadline="",
                date_verified=True, evidence_quote=f"项目{number}在原文中公布了新的具体进展。") | changes


def repo(number, pushed=DAY + "T10:00:00Z", **changes):
    return dict(full_name=f"owner/project{number}", html_url=f"https://github.com/owner/project{number}",
                description="An open source project", pushed_at=pushed, stargazers_count=1000,
                fork=False, archived=False, language="Python") | changes


class RecentNewsTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "data" / "test-tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.addCleanup(patch.stopall)
        patch("ribao.ROOT", self.root).start()
        patch("ribao.now", return_value=NOW).start()

    def receipt(self, day, parts, snapshots=None, webhook=None, suffix=""):
        destination = hashlib.sha256((webhook or KEYS["FEISHU_WEBHOOK_URL"]).encode()).hexdigest()[:16]
        state = {"parts": parts}
        if snapshots is not None:
            state["items_by_part"] = snapshots
        ribao.write_json(self.root / "data" / day / f"delivery-{destination}{suffix}.json", state)

    def test_rolling_month_includes_boundary_and_beijing_dates(self):
        self.assertEqual(month_start(DAY), "2026-10-01")
        for value in ("2026-10-01", "2026-10-29T17:00:00Z", DAY):
            self.assertTrue(in_window(value, DAY))
        for value in ("2026-09-30", "2026-10-31", "2026-10-30T17:00:00Z", "", None):
            self.assertFalse(in_window(value, DAY))
        ribao.validate_item(item(1, "2026-10-01"), DAY, {item(1)["url"]})

    def test_yesterday_precedes_higher_scoring_monthly_items_and_dedups(self):
        recent = item(1, score=1)
        old = item(2, "2026-10-29", score=100)
        duplicate = item(3, event_key=recent["event_key"], score=0)
        selected, _ = grounded.select_items([old, duplicate, recent], "ai_tech", DAY, StoryHistory())
        self.assertEqual([v["title"] for v in selected], [recent["title"], old["title"]])
        history = StoryHistory([recent])
        selected, _ = grounded.select_items([recent, old], "business", DAY, history)
        self.assertEqual(selected, [old])

    def test_receipts_scope_destination_sent_uncertain_and_window(self):
        sent, uncertain, failed, alien, expired = [item(i) for i in range(5)]
        self.receipt("2026-10-29", {"1": "sent", "2": "uncertain", "3": "failed"},
                     {"1": [sent], "2": [uncertain], "3": [failed]})
        self.receipt("2026-10-29", {"1": "sent"}, {"1": [alien]}, webhook="other-group")
        self.receipt("2026-09-30", {"1": "sent"}, {"1": [expired]})
        history = load_history(self.root, DAY, KEYS)
        self.assertTrue(history.contains(sent))
        self.assertTrue(history.contains(uncertain))
        for value in (failed, alien, expired):
            self.assertFalse(history.contains(value))
        rewritten = item(9, title="改写后的不同标题", url=sent["url"] + "?utm_source=x")
        self.assertTrue(history.contains(rewritten))

    def test_legacy_receipts_read_immutable_revision_instead_of_new_preview(self):
        old, revision, draft = item(1), item(2), item(3)
        folder = self.root / "data" / DAY
        ribao.write_json(folder / "report.json", {"sections": [{"items": [old]}]})
        ribao.write_json(folder / "revisions" / "abcdef012345" / "report.json", {"sections": [{"items": [revision]}]})
        ribao.write_json(folder / "review" / "report.json", {"sections": [{"items": [draft]}]})
        self.receipt(DAY, {"1": "sent"})
        self.receipt(DAY, {"1": "sent"}, suffix="-revision-abcdef012345")
        history = load_history(self.root, DAY, KEYS)
        self.assertTrue(history.contains(old))
        self.assertTrue(history.contains(revision))
        self.assertFalse(history.contains(draft))

    def test_distinct_events_in_one_digest_are_allowed_but_prior_url_is_excluded(self):
        one = item(1)
        two = item(2, url=one["url"])
        local = StoryHistory()
        local.add(one)
        self.assertFalse(local.contains(two))
        self.assertTrue(StoryHistory([one]).contains(two))
        project = github_hot.repository_item(repo(1), DAY)
        history = StoryHistory([project])
        project["url"] += "/releases/tag/v2"
        project.update(title="新标题", event_key="new-event")
        self.assertTrue(history.contains(project))

    def test_similar_titles_keep_distinct_release_numbers(self):
        one = item(1, title="开源开发工具发布正式版本2.1并新增功能")
        two = item(2, title="开源开发工具发布正式版本2.2并新增功能")
        self.assertFalse(StoryHistory([one]).contains(two))

    def test_combined_release_is_not_repeated_with_a_new_title_and_source(self):
        sent = item(1, title="智元发布具身基座模型GO-3 Preview及灵渠OS 1.0")
        duplicate = item(2, title="智元发布具身智能原生操作系统-灵渠OS1.0，将开源2亿行代码")
        new_version = item(3, title="智元发布具身智能原生操作系统-灵渠OS2.0")
        history = StoryHistory([sent])
        self.assertTrue(history.contains(duplicate))
        self.assertFalse(history.contains(new_version))

    def test_dividend_and_its_approval_are_one_event(self):
        one = item(1, title="财通证券拟每股派息0.07元，前三季度拟分红3.22亿元")
        two = item(2, title="财通证券召开董事会，审议通过三季度利润分配方案")
        three = item(3, title="财通证券将召开第三季度业绩说明会")
        history = StoryHistory([one])
        self.assertTrue(history.contains(two))
        self.assertFalse(history.contains(three))
        generic = item(4, title="均瑶健康召开第六届董事会，审议通过第三季度报告")
        self.assertTrue(grounded.section_candidate_error("business", generic))

    def test_wire_source_ranking_ads_are_removed_after_editing_too(self):
        ad = item(1, kind="supply", source_title="2026年安平可接工程急单的地热网片厂盘点")
        selected, rejected = grounded.select_items([ad], "anping_wire", DAY, StoryHistory())
        self.assertEqual(selected, [])
        self.assertEqual(len(rejected), 1)

    @patch("ribao.post_json", side_effect=ribao.BriefError("网络超时"))
    def test_uncertain_delivery_keeps_original_items_even_if_report_changes(self, post):
        value = dict(date=DAY, pipeline_version=3, sections=[
            dict(id=sid, title=sid, status="complete", items=[item(index)])
            for index, sid in enumerate(ribao.SECTIONS)])
        with self.assertRaises(ribao.BriefError):
            ribao.deliver(value, KEYS)
        ribao.write_json(self.root / "data" / DAY / "report.json", {"sections": []})
        history = load_history(self.root, DAY, KEYS)
        self.assertTrue(history.contains(item(0)))
        self.assertFalse(history.contains(item(1)))
        self.assertEqual(post.call_count, 1)

    def test_corrupt_history_stops_instead_of_forgetting_prior_sends(self):
        self.receipt(DAY, {"1": "sent"})
        with self.assertRaisesRegex(ribao.BriefError, "历史投递记录"):
            load_history(self.root, DAY, KEYS)

    def test_old_date_only_rejection_is_reclassified_but_network_failure_remains(self):
        cached = dict(published_at="2026-10-05", error="原文日期不是昨日")
        self.assertEqual(grounded.apply_date_window(cached, DAY)["error"], "")
        cached["error"] = "原文访问失败"
        self.assertEqual(grounded.apply_date_window(cached, DAY)["error"], "原文访问失败")

    def test_cards_end_each_item_with_link_and_omit_internal_counts(self):
        section = dict(id="ai_tech", title="AI", items=[item(1), item(2)], status="partial",
                       rejected_count=5, skipped_source_count=8, errors=["内部故障信息"])
        text = ribao.section_text(section)
        for index in (1, 2):
            self.assertIn(f"[原文链接](https://example.com/news/{index})", text)
        self.assertTrue(text.split("**2.")[0].strip().endswith(DAY))
        for value in ("未通过", "跳过", "其余暂无", "内部故障信息", "5", "8"):
            self.assertNotIn(value, text)
        section.update(items=[], status="complete")
        self.assertEqual(ribao.section_text(section), "暂无")

    def test_v3_requires_four_sections_while_legacy_three_remain_readable(self):
        report = dict(date=DAY, pipeline_version=3, sections=[
            dict(id=sid, title=sid, items=[], status="complete") for sid in ribao.SECTIONS])
        ribao.validate_report(report)
        report["sections"].pop()
        with self.assertRaises(ribao.BriefError):
            ribao.validate_report(report)
        report["pipeline_version"] = 2
        ribao.validate_report(report)

    @patch("github_hot.search_repositories")
    def test_github_yesterday_first_then_month_skips_prior_repos(self, search):
        previous = github_hot.repository_item(repo(0), DAY)
        search.side_effect = [dict(items=[repo(0), repo(1)]), dict(items=[repo(1), repo(2, "2026-10-10T10:00:00Z")])]
        selected, errors = github_hot.collect_items(DAY, StoryHistory([previous]), self.root)
        self.assertEqual(errors, [])
        self.assertEqual([v["title"] for v in selected], ["owner/project1", "owner/project2"])
        self.assertEqual([call.args for call in search.call_args_list], [(DAY, DAY), ("2026-10-01", DAY)])
        self.assertIsNone(github_hot.repository_item(repo(3, "2026-09-30T00:00:00Z"), DAY))
        self.assertIsNone(github_hot.repository_item(repo(4, archived=True), DAY))
        with self.assertRaises(ribao.BriefError):
            github_hot.repository_item(repo(5, html_url="https://other.example/owner/project5"), DAY)

    @patch("github_hot.search_repositories")
    def test_github_stops_at_ten_without_month_call(self, search):
        search.return_value = dict(items=[repo(i) for i in range(15)])
        selected, errors = github_hot.collect_items(DAY, StoryHistory(), self.root)
        self.assertEqual(len(selected), 10)
        self.assertEqual(errors, [])
        self.assertEqual(search.call_count, 1)

    @patch("ribao.post_json")
    @patch("grounded.fetch_source")
    def test_news_shortfall_fetches_month_once_and_keeps_yesterday_priority(self, fetch, post):
        config = dict(model="qwen-plus", region="cn-beijing", workspace_id="ws-test", max_tokens=5000, search_strategy="max",
                      timeout_seconds=180, sections=[dict(id="ai_tech", title="AI", queries=["yesterday"], month_query="month")])
        seen_month_payloads = []
        def api(url, payload, headers, timeout):
            if payload["parameters"]["enable_search"]:
                monthly = "近一个月发布" in payload["input"]["messages"][-1]["content"]
                if monthly:
                    seen_month_payloads.append(payload)
                sources = [dict(url=item(i)["url"], title=f"文章{i}") for i in ([1, 2] if monthly else [1])]
                return {"output": {"search_info": {"search_results": sources}}}
            text = payload["input"]["messages"][-1]["content"].split("文章资料如下：\n")[1]
            documents = json.loads(text)
            values = []
            for document in documents:
                number = int(document["title"][-1])
                values.append(item(number, source_id=document["source_id"], evidence_quote=document["text"][:20], score=100 if number == 2 else 1))
            return {"output": {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"items": values})}}]}}
        post.side_effect = api
        def article(source, target, folder):
            number = int(source["title"][-1])
            return dict(source, source="来源", text="这是可以逐字回查的真实文章证据内容。" * 5,
                        published_at=DAY if number == 1 else "2026-10-05", error="")
        fetch.side_effect = article
        report = grounded.generate_report(config, KEYS, DAY)
        self.assertEqual([v["published_at"] for v in report["sections"][0]["items"]], [DAY, "2026-10-05"])
        self.assertEqual(len(seen_month_payloads), 1)
        self.assertEqual(post.call_count, 4)  # Two bounded searches and two grounded edits.


if __name__ == "__main__":
    unittest.main()
