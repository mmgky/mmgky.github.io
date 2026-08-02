#!/usr/bin/env python3
"""Build a static PDF cover gallery for GitHub Pages."""

from __future__ import annotations

import hashlib
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_site"
CONFIG_PATH = ROOT / "site-config.json"


def abort(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_config() -> dict[str, str]:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        abort("site-config.json is missing.")
    except json.JSONDecodeError as exc:
        abort(f"site-config.json is invalid: {exc}")

    required = (
        "title",
        "description",
        "owner",
        "repository",
        "pdf_directory",
        "uncategorized_name",
    )
    missing = [key for key in required if not str(data.get(key, "")).strip()]
    if missing:
        abort("Missing config fields: " + ", ".join(missing))

    return {key: str(value).strip() for key, value in data.items()}


def find_pdfs(pdf_root: Path) -> list[Path]:
    pdf_root.mkdir(parents=True, exist_ok=True)
    return sorted(
        (
            path
            for path in pdf_root.rglob("*")
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.casefold() == ".pdf"
        ),
        key=lambda path: str(path.relative_to(pdf_root)).casefold(),
    )


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            digits = 0 if value >= 100 else 1 if value >= 10 else 2
            return f"{value:.{digits}f} {unit}"
        value /= 1024
    return f"{size} B"


def encode_path(path: Path) -> str:
    return "/".join(quote(part, safe="") for part in path.parts)


def category_for(path: Path, pdf_root: Path, fallback: str) -> str:
    parent = path.relative_to(pdf_root).parent
    if str(parent) == ".":
        return fallback
    return " / ".join(parent.parts)


def create_placeholder(path: Path, title: str) -> None:
    safe_title = html.escape(title[:48])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1200" viewBox="0 0 900 1200">
  <rect width="900" height="1200" fill="#eef2f6"/>
  <rect x="120" y="110" width="660" height="880" rx="28" fill="#ffffff" stroke="#d5dce5" stroke-width="5"/>
  <rect x="170" y="190" width="140" height="64" rx="12" fill="#fee2e2"/>
  <text x="240" y="234" text-anchor="middle" font-family="Arial" font-size="34" font-weight="700" fill="#b91c1c">PDF</text>
  <text x="450" y="570" text-anchor="middle" font-family="Arial, sans-serif" font-size="36" fill="#334155">{safe_title}</text>
  <text x="450" y="625" text-anchor="middle" font-family="Arial, sans-serif" font-size="23" fill="#94a3b8">暂无封面预览</text>
</svg>"""
    path.write_text(svg, encoding="utf-8")


def generate_cover(pdf: Path, cover_base: Path, title: str) -> Path:
    jpeg_path = cover_base.with_suffix(".jpg")
    svg_path = cover_base.with_suffix(".svg")

    tool = shutil.which("pdftoppm")
    if tool:
        result = subprocess.run(
            [
                tool,
                "-f", "1",
                "-l", "1",
                "-singlefile",
                "-jpeg",
                "-r", "120",
                str(pdf),
                str(cover_base),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and jpeg_path.exists():
            return jpeg_path

    create_placeholder(svg_path, title)
    return svg_path


def render_card(
    pdf: Path,
    pdf_root: Path,
    output_pdf_root: Path,
    cover_root: Path,
    config: dict[str, str],
) -> str:
    relative = pdf.relative_to(pdf_root)
    target_pdf = output_pdf_root / relative
    target_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf, target_pdf)

    title = pdf.stem.strip() or pdf.name
    category = category_for(pdf, pdf_root, config["uncategorized_name"])
    size = format_size(pdf.stat().st_size)

    cover_name = hashlib.sha256(str(relative).encode("utf-8")).hexdigest()[:20]
    cover = generate_cover(pdf, cover_root / cover_name, title)

    pdf_url = "./" + encode_path(Path(config["pdf_directory"]) / relative)
    cover_url = "./covers/" + quote(cover.name, safe="")

    search_value = " ".join((title, pdf.name, category)).casefold()

    return f"""<article class="pdf-card" data-search="{html.escape(search_value, quote=True)}">
  <a class="cover-link" href="{pdf_url}" target="_blank" rel="noopener">
    <img class="cover"
         src="{cover_url}"
         alt="{html.escape(title)} 首页预览"
         loading="lazy">
  </a>
  <div class="card-body">
    <span class="category">{html.escape(category)}</span>
    <h2 class="card-title" title="{html.escape(title, quote=True)}">{html.escape(title)}</h2>
    <p class="meta">{html.escape(size)}</p>
    <div class="actions">
      <a class="button primary" href="{pdf_url}" target="_blank" rel="noopener">打开</a>
      <a class="button" href="{pdf_url}" download>下载</a>
    </div>
  </div>
</article>"""


def render_page(config: dict[str, str], cards: list[str]) -> str:
    count = len(cards)
    if cards:
        content = '<main class="gallery" id="gallery">\n' + "\n".join(cards) + "\n</main>"
    else:
        content = """<main class="empty">
  <strong>暂时没有 PDF</strong>
  把文件上传到 <code>pdf/</code> 后提交，Actions 会自动生成封面画册。
</main>"""

    script = """
<script>
  const input = document.getElementById('search');
  const cards = Array.from(document.querySelectorAll('.pdf-card'));
  const count = document.getElementById('result-count');

  function updateGallery() {
    const keyword = input.value.trim().toLocaleLowerCase();
    let visible = 0;

    for (const card of cards) {
      const matched = !keyword || card.dataset.search.includes(keyword);
      card.hidden = !matched;
      if (matched) visible += 1;
    }

    count.textContent = `显示 ${visible} / ${cards.length}`;
  }

  input?.addEventListener('input', updateGallery);
  updateGallery();
</script>
""" if cards else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{html.escape(config['description'], quote=True)}">
  <meta name="theme-color" content="#1769e0">
  <title>{html.escape(config['title'])}</title>
  <link rel="icon" href="./favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="./styles.css">
</head>
<body>
  <div class="page">
    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">PDF Gallery</p>
        <h1>{html.escape(config['title'])}</h1>
        <p class="description">{html.escape(config['description'])}</p>
      </div>
      <a class="repo-link"
         href="https://github.com/{quote(config['owner'])}/{quote(config['repository'])}"
         target="_blank"
         rel="noopener">
        GitHub 仓库
      </a>
    </header>

    <section class="toolbar" aria-label="筛选文档">
      <input class="search"
             id="search"
             type="search"
             placeholder="搜索标题或分类"
             autocomplete="off">
      <span class="result-count" id="result-count">共 {count} 份</span>
    </section>

    {content}

    <footer class="footer">由 GitHub Actions 自动生成 PDF 首页预览</footer>
  </div>
  {script}
</body>
</html>
"""


def main() -> None:
    config = load_config()

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)

    cover_root = OUTPUT / "covers"
    output_pdf_root = OUTPUT / config["pdf_directory"]
    cover_root.mkdir(parents=True)
    output_pdf_root.mkdir(parents=True)

    for filename in ("styles.css", "favicon.svg", ".nojekyll"):
        source = ROOT / filename
        if not source.exists():
            abort(f"Required file is missing: {filename}")
        shutil.copy2(source, OUTPUT / filename)

    pdf_root = ROOT / config["pdf_directory"]
    pdfs = find_pdfs(pdf_root)

    cards = [
        render_card(pdf, pdf_root, output_pdf_root, cover_root, config)
        for pdf in pdfs
    ]

    index = render_page(config, cards)
    (OUTPUT / "index.html").write_text(index, encoding="utf-8")
    (OUTPUT / "404.html").write_text(index, encoding="utf-8")
    (OUTPUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n",
        encoding="utf-8",
    )

    print(f"Built gallery with {len(pdfs)} PDF file(s).")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
