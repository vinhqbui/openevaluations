"""Every internal link of the static site lands on a file or a redirect, and none points at the old product pages."""

import re
from html.parser import HTMLParser

from oe import REPO

SITE = REPO / "site"
ORIGIN = "https://openevaluations.si"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src") and value and value.startswith("/") and not value.startswith("//"):
                self.urls.append(value)


def _redirect_sources():
    path = SITE / "_redirects"
    if not path.exists():
        return set(), []
    exact, prefixes = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        source = line.split()[0]
        if source.endswith("*"):
            prefixes.append(source[:-1])
        else:
            exact.add(source)
    return exact, prefixes


def _resolves(url):
    path = re.split(r"[?#]", url, maxsplit=1)[0]
    exact, prefixes = _redirect_sources()
    if path in exact or any(path.startswith(p) for p in prefixes):
        return True
    rel = path.lstrip("/")
    if path.endswith("/"):
        return (SITE / rel / "index.html").is_file()
    return any((SITE / c).is_file() for c in (rel, rel + ".html", rel + "/index.html"))


def _pages():
    return sorted(p for p in SITE.rglob("*.html") if "data" not in p.relative_to(SITE).parts)


def test_every_internal_link_in_the_site_resolves():
    broken = []
    for page in _pages():
        parser = _Links()
        parser.feed(page.read_text(encoding="utf-8"))
        broken += [f"{page.relative_to(SITE).as_posix()}: {u}" for u in parser.urls if not _resolves(u)]
    assert broken == []


def test_every_sitemap_url_resolves():
    locs = re.findall(r"<loc>(.*?)</loc>", (SITE / "sitemap.xml").read_text(encoding="utf-8"))
    assert locs
    ours = [u for u in locs if u.startswith(ORIGIN + "/")]
    assert ours == locs
    assert [u for u in ours if not _resolves(u[len(ORIGIN):])] == []


def test_no_page_links_to_the_old_product_pages():
    hits = [
        f"{page.relative_to(SITE).as_posix()}: {needle}"
        for page in _pages()
        for needle in ('href="/scholion', "scholion.openevaluations.si")
        if needle in page.read_text(encoding="utf-8")
    ]
    assert hits == []
