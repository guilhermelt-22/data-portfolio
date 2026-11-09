"""Build the GitHub Pages site from the repository's own README files (single source of truth).

README.md            -> index.html
data/README.md       -> data/index.html
cases/*/README.md    -> cases/*/index.html

Links are rewritten so they work on the site: README links become page links, code and folder
links point to the GitHub file viewer, and data files (xlsx, csv, html, png) stay relative.

Usage:  python site/build.py
"""
from __future__ import annotations

import html
import re
from pathlib import Path, PurePosixPath

import markdown

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/guilhermelt-22/data-portfolio"
CODE_SUFFIXES = {".py", ".sql", ".toml", ".md"}
PAGES = [ROOT / "README.md", ROOT / "data" / "README.md", *sorted((ROOT / "cases").glob("*/README.md"))]

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="Data cleaning, ETL, automation, web scraping and dashboards in Python, SQL, Excel and Looker Studio, with every number checked against its source.">
<style>
  :root {{ color-scheme: light; --page:#f9f9f7; --surface:#ffffff; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
          --line:#e1e0d9; --accent:#2a78d6; --code:#f3f2ee; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
            --line:#2c2c2a; --accent:#3987e5; --code:#232322; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--page); color:var(--ink); font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  header {{ border-bottom:1px solid var(--line); background:var(--surface); }}
  .bar {{ max-width:980px; margin:0 auto; padding:12px 16px; display:flex; gap:16px; align-items:center; flex-wrap:wrap; }}
  .brand {{ font-weight:700; color:var(--ink); text-decoration:none; margin-right:auto; }}
  .bar a.nav {{ color:var(--ink2); text-decoration:none; font-size:15px; }}
  .bar a.nav:hover {{ color:var(--accent); }}
  main {{ max-width:980px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:30px; line-height:1.25; margin:8px 0 16px; }}
  h2 {{ font-size:22px; margin:36px 0 12px; padding-top:8px; border-top:1px solid var(--line); }}
  a {{ color:var(--accent); }}
  img {{ max-width:100%; height:auto; border:1px solid var(--line); border-radius:8px; }}
  blockquote {{ margin:16px 0; padding:10px 16px; border-left:4px solid var(--accent); background:var(--surface); color:var(--ink2); }}
  blockquote p {{ margin:4px 0; }}
  .table-wrap {{ overflow-x:auto; margin:16px 0; }}
  table {{ border-collapse:collapse; width:100%; font-size:15px; background:var(--surface); }}
  th, td {{ border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }}
  th {{ background:var(--code); }}
  td img {{ border:none; }}
  code {{ background:var(--code); padding:1px 5px; border-radius:4px; font-size:14px; }}
  pre {{ background:var(--code); padding:12px 14px; border-radius:8px; overflow-x:auto; }}
  pre code {{ padding:0; background:none; }}
  pre.mermaid {{ background:var(--surface); border:1px solid var(--line); text-align:center; }}
  footer {{ max-width:980px; margin:0 auto; padding:16px 16px 40px; color:var(--muted); font-size:13px; border-top:1px solid var(--line); }}
</style>
</head>
<body>
<header><div class="bar">
  <a class="brand" href="{root}">Guilherme Teófilo · Data analyst</a>
  <a class="nav" href="{root}#case-studies">Case studies</a>
  <a class="nav" href="{root}output/2026-10/dashboard.html">Live dashboard</a>
  <a class="nav" href="{repo}">Code on GitHub</a>
</div></header>
<main>
{body}
</main>
<footer>All companies, people and figures on this site are fictitious demo data.</footer>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs";
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  mermaid.initialize({{ startOnLoad: true, theme: dark ? "dark" : "neutral" }});
</script>
</body>
</html>
"""


def rewrite_link(href: str, page_dir: PurePosixPath) -> str:
    if re.match(r"^(https?:|mailto:|#)", href):
        return href
    path, _, anchor = href.partition("#")
    target = PurePosixPath(*(page_dir / path).parts)  # repo-relative, may contain '..'
    parts: list[str] = []
    for p in target.parts:
        if p == "..":
            parts.pop()
        elif p != ".":
            parts.append(p)
    resolved = PurePosixPath(*parts) if parts else PurePosixPath(".")
    suffix = f"#{anchor}" if anchor else ""
    if resolved.name == "README.md":
        return href[: -len("README.md")] if not anchor else path[: -len("README.md")] + suffix
    if (ROOT / resolved).is_dir():
        return f"{REPO_URL}/tree/main/{resolved.as_posix()}"
    if resolved.suffix in CODE_SUFFIXES:
        return f"{REPO_URL}/blob/main/{resolved.as_posix()}{suffix}"
    return href


def render(readme: Path) -> Path:
    rel_dir = PurePosixPath(readme.parent.relative_to(ROOT).as_posix())
    depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
    root = "../" * depth or "./"
    text = readme.read_text(encoding="utf-8")
    title = re.search(r"^# (.+)$", text, re.M).group(1)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"])
    body = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>',
                  lambda m: f'<pre class="mermaid">{html.unescape(m.group(1))}</pre>', body, flags=re.S)
    body = re.sub(r'(href|src)="([^"]+)"',
                  lambda m: f'{m.group(1)}="{rewrite_link(m.group(2), rel_dir) if m.group(1) == "href" else m.group(2)}"',
                  body)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    out = readme.parent / "index.html"
    page_title = "Data analyst portfolio · Guilherme Teófilo" if depth == 0 else f"{title} · Guilherme Teófilo"
    out.write_text(TEMPLATE.format(title=html.escape(page_title), root=root, repo=REPO_URL, body=body),
                   encoding="utf-8")
    return out


def main() -> None:
    (ROOT / ".nojekyll").touch()  # serve files as-is (no Jekyll processing on GitHub Pages)
    for page in PAGES:
        print(render(page).relative_to(ROOT))


if __name__ == "__main__":
    main()
