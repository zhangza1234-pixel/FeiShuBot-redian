from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import github_hot
import grounded
import ribao


DAY = "2026-10-30"
TEXT = "A command-line tool to download videos and audio from supported websites."


def project():
    return dict(title="owner/downloader", summary=TEXT, why="旧推荐理由", source="GitHub",
                url="https://github.com/owner/downloader", published_at=DAY, event_key="repo:owner/downloader",
                kind="repository", score=90, stars=1000, details="累计 ⭐ 1,000 · Python", deadline="", date_verified=True)


def response(**changes):
    value = dict(source_id="g1", purpose="这是命令行下载工具，可以将支持网站的视频或音频保存到本地。",
                 audience="愿意使用命令行、需要整理音视频资料的人。",
                 use_case="例如：把自己有权下载的教学视频保存到电脑，方便离线复习。", evidence_quote=TEXT)
    value.update(changes)
    return {"output": {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"items": [value]})}}]}}


class GitHubExplanationTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / "data" / "test-tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.config = dict(model="qwen-plus", region="cn-beijing", workspace_id="ws-test", max_tokens=5000, timeout_seconds=180)
        self.documents = [dict(source_id="g1", name="owner/downloader", text=TEXT)]

    def test_purpose_audience_scenario_are_chinese_and_metadata_stays_bound(self):
        items, errors = github_hot.parse_explanations(response(url="https://fake.example/", stars=999999,
            title="伪造项目"), self.documents, [project()], DAY)
        self.assertEqual(errors, [])
        value = items[0]
        self.assertEqual(value["url"], project()["url"])
        self.assertEqual(value["stars"], 1000)
        self.assertEqual(value["title"], project()["title"])
        text = ribao.section_text(dict(items=items, status="complete"))
        for label in ("用途：", "适合谁：", "使用场景：", "离线复习", "[GitHub 仓库](https://github.com/owner/downloader)"):
            self.assertIn(label, text)
        self.assertNotIn("关注理由", text)
        self.assertNotIn(TEXT, text)

    def test_english_only_fabricated_evidence_and_unknown_sources_are_not_published(self):
        for changes in (dict(purpose=TEXT), dict(evidence_quote="Invented functionality not in README."),
                        dict(source_id="unknown"), dict(use_case="Try it yourself")):
            with self.subTest(changes=changes):
                items, errors = github_hot.parse_explanations(response(**changes), self.documents, [project()], DAY)
                self.assertEqual(items, [])
                self.assertTrue(errors)

    def test_evidence_is_bound_by_program_from_fixed_readme_fragment(self):
        documents = [dict(self.documents[0], evidence_options=[dict(id="p1", quote=TEXT)])]
        values, errors = github_hot.parse_explanations(response(evidence_id="p1", evidence_quote="伪造引用"), documents, [project()], DAY)
        self.assertEqual(errors, [])
        self.assertEqual(values[0]["evidence_quote"], TEXT)
        values, errors = github_hot.parse_explanations(response(evidence_id="invented"), documents, [project()], DAY)
        self.assertEqual(values, [])
        self.assertTrue(errors)

    def test_output_order_preserves_repository_ranking(self):
        second = dict(project(), title="owner/second", url="https://github.com/owner/second")
        documents = self.documents + [dict(source_id="g2", name="owner/second", text=TEXT)]
        reply = response()
        choice = reply["output"]["choices"][0]
        original = json.loads(choice["message"]["content"])["items"][0]
        choice["message"]["content"] = json.dumps({"items": [dict(original, source_id="g2"), original]})
        items, _ = github_hot.parse_explanations(reply, documents, [project(), second], DAY)
        self.assertEqual([v["title"] for v in items], ["owner/downloader", "owner/second"])

    @patch("github_hot.readme_text", return_value=TEXT)
    @patch("ribao.post_json", return_value=response())
    def test_one_batch_call_and_unchanged_preview_reuses_cached_explanation(self, post, readme):
        for _ in range(2):
            values, errors = github_hot.explain_items([project()], self.config, {"DASHSCOPE_API_KEY": "test-key"}, DAY, self.folder)
            self.assertEqual(len(values), 1)
            self.assertEqual(errors, [])
        self.assertEqual(post.call_count, 1)
        self.assertFalse(post.call_args.args[1]["parameters"]["enable_search"])

    @patch("github_hot.readme_text", return_value=TEXT)
    @patch("ribao.post_json", side_effect=ribao.BriefError("API暂不可用"))
    def test_model_failure_does_not_fall_back_to_english_or_generic_advice(self, post, readme):
        items, errors = github_hot.explain_items([project()], self.config, {"DASHSCOPE_API_KEY": "test-key"}, DAY, self.folder)
        self.assertEqual(items, [])
        self.assertEqual(errors, ["API暂不可用"])

    @patch("github_hot.readme_text", side_effect=ribao.BriefError("README不可达"))
    @patch("ribao.post_json", return_value=response())
    def test_rich_repository_description_can_support_explanation_without_readme(self, post, readme):
        items, errors = github_hot.explain_items([project()], self.config, {"DASHSCOPE_API_KEY": "test-key"}, DAY, self.folder)
        self.assertEqual(len(items), 1)
        self.assertEqual(errors, [])
        sources = ribao.read_json(self.folder / "github-explanations.sources.json")
        self.assertEqual(sources[0]["readme_error"], "README不可达")

    @patch("ribao.post_json")
    def test_empty_section_does_not_spend_model_call(self, post):
        self.assertEqual(github_hot.explain_items([], self.config, {}, DAY, self.folder), ([], []))
        post.assert_not_called()

    @patch("github_hot.urllib.request.build_opener")
    def test_repository_path_is_checked_before_readme_fetch(self, opener):
        with self.assertRaises(ribao.BriefError):
            github_hot.readme_text(dict(project(), url="https://github.com/owner/../other"), self.folder)
        opener.assert_not_called()

    @patch("github_hot.urllib.request.build_opener")
    def test_api_fallback_and_cache_for_repo_with_differently_named_readme(self, opener):
        connection = opener.return_value.open
        result = unittest.mock.MagicMock()
        result.__enter__.return_value.read.return_value = TEXT.encode()
        connection.side_effect = [urllib.error.HTTPError("https://raw.githubusercontent.com/owner/downloader/HEAD/README.md", 404, "missing", {}, None), result]
        self.assertEqual(github_hot.readme_text(project(), self.folder), TEXT)
        self.assertEqual(github_hot.readme_text(project(), self.folder), TEXT)
        self.assertEqual(connection.call_count, 2)
        self.assertIn("api.github.com/repos/owner/downloader/readme", connection.call_args.args[0].full_url)

    @patch("github_hot.collect_items", return_value=([project()], []))
    @patch("github_hot.explain_items")
    def test_daily_generation_stores_explained_items_in_github_section(self, explain, collect):
        ready, _ = github_hot.parse_explanations(response(), self.documents, [project()], DAY)
        explain.return_value = ready, []
        config = dict(self.config, sections=[dict(id="github_hot", title="GitHub 热点", provider="github")])
        with patch("ribao.ROOT", self.folder), patch("ribao.now", return_value=datetime(2026, 10, 31, 8, 30, tzinfo=ribao.SHANGHAI)):
            result = grounded.generate_report(config, {"DASHSCOPE_API_KEY": "test-key"}, DAY)
        self.assertTrue(result["sections"][0]["items"][0]["github_explained"])
        explain.assert_called_once()


if __name__ == "__main__":
    unittest.main()
