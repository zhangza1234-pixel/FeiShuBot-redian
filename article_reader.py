"""Extract visible article text without executing page scripts."""
from html.parser import HTMLParser
import html
import re


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = []
        self.blocks = []
        self.title = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"meta", "link", "img", "br", "hr", "input", "source", "wbr"}:
            return
        blocked = tag in {"script", "style", "nav", "footer", "noscript", "svg"}
        blocked = blocked or any(frame[1] for frame in self.stack)
        marker = " ".join((attrs.get("id", ""), attrs.get("class", "")))
        preferred = tag == "article" or bool(re.search(
            r"(?:^|\s)(?:artibody|ozoom|article[-_]?(?:body|content|main)|news[-_]?(?:text|content)|content-body)(?:\s|$)", marker, re.I))
        frame = (tag, blocked, [] if preferred else None)
        self.stack.append(frame)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                for _, blocked, block in self.stack[index:]:
                    if block and not blocked:
                        self.blocks.append(" ".join(block))
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(frame[1] for frame in self.stack):
            return
        value = data.strip()
        if not value:
            return
        if any(frame[0] in {"title", "h1"} for frame in self.stack):
            self.title.append(value)
        if not any(frame[0] == "head" for frame in self.stack):
            self.text.append(value)
            for _, _, block in self.stack:
                if block is not None:
                    block.append(value)


def article_text(document):
    # Chinese newspaper pages explicitly mark their main article.
    newspaper = re.search(r"<!--\s*enpcontent\s*-->(.*?)<!--\s*/enpcontent\s*-->", document, re.S | re.I)
    parser = ArticleParser()
    parser.feed(newspaper.group(1) if newspaper else document)
    parser.close()
    content = max(parser.blocks, key=len) if parser.blocks else " ".join(parser.text)
    return {"title": re.sub(r"\s+", " ", " ".join(parser.title)),
            "text": re.sub(r"\s+", " ", html.unescape(content)).strip()}
