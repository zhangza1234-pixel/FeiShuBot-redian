"""Deduplicate against actual sent/uncertain card receipts, scoped to destination."""
from datetime import date, timedelta
from difflib import SequenceMatcher
import hashlib
import re
import unicodedata
import urllib.parse


def month_start(target):
    return (date.fromisoformat(target) - timedelta(days=29)).isoformat()


def in_window(published, target):
    try:
        from ribao import iso_day
        return month_start(target) <= iso_day(published) <= target
    except (ValueError, TypeError):
        return False


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(value))).lower()


def event_signatures(item):
    title = item.get("title", "")
    signatures = set()
    company = re.match(r"^(.{2,16}?(?:股份|集团|科技|证券|银行|健康|实业|能源|控股|公司))", title)
    # A dividend proposal and the board meeting approving it are one story.
    if company and re.search(r"分红|派息|利润分配|股息", title):
        signatures.add("dividend:" + normalized(company[1]))
    subject = re.match(r"^(.{2,16}?)(?:发布|推出|开源|官宣|宣布)", title)
    if subject:
        for version in re.findall(r"[a-z][a-z0-9_-]*\s*\d+(?:\.\d+){0,3}", title, re.I):
            signatures.add("release:" + normalized(subject[1]) + ":" + normalized(version))
    return signatures


def link_key(value):
    from ribao import canonical_url
    value = canonical_url(value)
    parsed = urllib.parse.urlsplit(value)
    if parsed.hostname in {"github.com", "www.github.com"}:
        pieces = parsed.path.strip("/").split("/")
        if len(pieces) >= 2:
            return "https://github.com/" + "/".join(pieces[:2]).removesuffix(".git").lower()
    return value


class StoryHistory:
    def __init__(self, previous=()):
        self.past_urls = set()
        self.events = set()
        self.signatures = set()
        self.titles = set()
        self.evidence = set()
        self.previous_titles = []
        for item in previous:
            try:
                self.past_urls.add(link_key(item["url"]))
                self.previous_titles.append(item["title"])
                self.add(item)
            except (KeyError, ValueError, TypeError):
                continue

    def contains(self, item):
        try:
            link = link_key(item["url"])
        except (KeyError, ValueError, TypeError):
            return True
        title, event = normalized(item.get("title", "")), normalized(item.get("event_key", ""))
        if link in self.past_urls or event and event in self.events or title in self.titles:
            return True
        if event_signatures(item) & self.signatures:
            return True
        if (link, item.get("evidence_quote", "")) in self.evidence:
            return True
        # Repository names and version/announcement numbers identify distinct items.
        if item.get("kind") == "repository":
            return False
        for previous in self.titles:
            if min(len(title), len(previous)) < 12:
                continue
            if min(len(title), len(previous)) / max(len(title), len(previous)) < 0.8:
                continue
            if re.findall(r"\d+", title) != re.findall(r"\d+", previous):
                continue
            if SequenceMatcher(None, title, previous).ratio() >= 0.88:
                return True
        return False

    def add(self, item):
        self.events.add(normalized(item.get("event_key", "")))
        self.signatures.update(event_signatures(item))
        self.titles.add(normalized(item.get("title", "")))
        self.evidence.add((link_key(item["url"]), item.get("evidence_quote", "")))


def load_history(root, target, credentials):
    import ribao as app
    webhook = credentials.get("FEISHU_WEBHOOK_URL")
    if not webhook:
        return StoryHistory()
    destination = hashlib.sha256(webhook.encode()).hexdigest()[:16]
    previous = []
    data = root / "data"
    if not data.exists():
        return StoryHistory()
    for folder in sorted(data.iterdir()):
        if not folder.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", folder.name):
            continue
        if not month_start(target) <= folder.name <= target:
            continue
        for receipt in folder.glob(f"delivery-{destination}*.json"):
            try:
                state = app.read_json(receipt)
                snapshots = state.get("items_by_part", {})
                if not snapshots:
                    revision = re.search(r"-revision-([0-9a-f]{12})\.json$", receipt.name)
                    report_path = folder / "revisions" / revision[1] / "report.json" if revision else folder / "report.json"
                    report = app.read_json(report_path)
                    snapshots = {str(i + 1): section["items"] for i, section in enumerate(report["sections"])}
                for part, status in state.get("parts", {}).items():
                    if status in {"sent", "uncertain"}:
                        previous.extend(snapshots.get(part, []))
            except (OSError, ValueError, KeyError, TypeError):
                # Never silently forget delivery history and resend old content.
                raise app.BriefError("历史投递记录无法读取，请检查本地记录后再生成") from None
    return StoryHistory(previous)
