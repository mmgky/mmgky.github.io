#!/usr/bin/env python3
"""构建纯静态 PDF 画册站点。

功能：
1. 扫描 pdf/ 及其子目录中的 PDF。
2. 使用 pdftoppm 生成每份 PDF 的第一页缩略图。
3. 生成无侧边栏的画册首页。
4. 预览按钮打开 viewer.html，由 PDF.js 在网页内渲染。
5. 下载按钮使用 ghfast.top 等代理加速 GitHub Raw 文件。
6. 输出完整站点到 _site/，供 GitHub Pages Actions 部署。

仅依赖 Python 标准库。
GitHub Actions 中需要安装 poppler-utils，以提供 pdftoppm。
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlencode


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_site"
CONFIG_PATH = ROOT / "site-config.json"

# 这些文件必须位于仓库根目录，并会被复制到最终站点。
STATIC_FILES = (
    "styles.css",
    "favicon.svg",
    "viewer.html",
    ".nojekyll",
)


def abort(message: str) -> None:
    """输出错误并终止构建。"""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_config() -> dict[str, str]:
    """读取并校验 site-config.json。"""
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        abort("找不到 site-config.json。")
    except json.JSONDecodeError as exc:
        abort(f"site-config.json 格式错误：{exc}")

    required = (
        "title",
        "description",
        "owner",
        "repository",
        "branch",
        "pdf_directory",
        "uncategorized_name",
        "download_proxy",
    )

    missing = [
        key
        for key in required
        if not str(data.get(key, "")).strip()
    ]

    if missing:
        abort(
            "site-config.json 缺少必需字段："
            + ", ".join(missing)
        )

    return {
        key: str(value).strip()
        for key, value in data.items()
    }


def find_pdfs(pdf_root: Path) -> list[Path]:
    """递归查找 PDF，忽略隐藏文件。"""
    pdf_root.mkdir(parents=True, exist_ok=True)

    return sorted(
        (
            path
            for path in pdf_root.rglob("*")
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.casefold() == ".pdf"
        ),
        key=lambda path: str(
            path.relative_to(pdf_root)
        ).casefold(),
    )


def format_size(byte_count: int) -> str:
    """把字节数转换为便于阅读的文件大小。"""
    value = float(byte_count)

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"

            decimals = (
                0
                if value >= 100
                else 1
                if value >= 10
                else 2
            )
            return f"{value:.{decimals}f} {unit}"

        value /= 1024

    return f"{byte_count} B"


def encode_path(path: Path) -> str:
    """逐段编码 URL 路径，兼容中文、空格和特殊字符。"""
    return "/".join(
        quote(part, safe="")
        for part in path.parts
    )


def category_for(
    pdf: Path,
    pdf_root: Path,
    fallback: str,
) -> str:
    """将 PDF 的父目录转换为分类名称。"""
    parent = pdf.relative_to(pdf_root).parent

    if str(parent) == ".":
        return fallback

    return " / ".join(parent.parts)


def create_placeholder(
    output_path: Path,
    title: str,
) -> None:
    """PDF 首页无法生成时，创建 SVG 占位封面。"""
    safe_title = html.escape(title[:42])

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
     width="900"
     height="1200"
     viewBox="0 0 900 1200">
  <rect width="900" height="1200" fill="#eef2f6"/>
  <rect x="120"
        y="110"
        width="660"
        height="880"
        rx="28"
        fill="#ffffff"
        stroke="#d5dce5"
        stroke-width="5"/>
  <rect x="170"
        y="190"
        width="140"
        height="64"
        rx="12"
        fill="#fee2e2"/>
  <text x="240"
        y="234"
        text-anchor="middle"
        font-family="Arial, sans-serif"
        font-size="34"
        font-weight="700"
        fill="#b91c1c">
    PDF
  </text>
  <text x="450"
        y="570"
        text-anchor="middle"
        font-family="Arial, sans-serif"
        font-size="34"
        fill="#334155">
    {safe_title}
  </text>
  <text x="450"
        y="625"
        text-anchor="middle"
        font-family="Arial, sans-serif"
        font-size="23"
        fill="#94a3b8">
    暂无封面预览
  </text>
</svg>
"""

    output_path.write_text(
        svg,
        encoding="utf-8",
    )


def generate_cover(
    pdf: Path,
    cover_base: Path,
    title: str,
) -> Path:
    """提取 PDF 第一页为 JPEG；失败时返回 SVG 占位图。"""
    jpeg_path = cover_base.with_suffix(".jpg")
    svg_path = cover_base.with_suffix(".svg")

    pdftoppm = shutil.which("pdftoppm")

    if pdftoppm:
        result = subprocess.run(
            [
                pdftoppm,
                "-f",
                "1",
                "-l",
                "1",
                "-singlefile",
                "-jpeg",
                "-jpegopt",
                "quality=84,optimize=y",
                "-r",
                "120",
                str(pdf),
                str(cover_base),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if (
            result.returncode == 0
            and jpeg_path.is_file()
        ):
            return jpeg_path

        print(
            f"WARNING: 无法生成封面：{pdf}",
            file=sys.stderr,
        )

        if result.stderr.strip():
            print(
                result.stderr.strip(),
                file=sys.stderr,
            )

    else:
        print(
            "WARNING: 未找到 pdftoppm，使用占位封面。",
            file=sys.stderr,
        )

    create_placeholder(svg_path, title)
    return svg_path


def build_raw_url(
    config: dict[str, str],
    pdf_path: Path,
) -> str:
    """生成指向当前提交中 PDF 的 GitHub Raw 地址。"""
    # GitHub Actions 会自动提供 GITHUB_SHA。
    # 本地构建时回退到配置中的 branch。
    raw_ref = os.environ.get(
        "GITHUB_SHA",
        config["branch"],
    ).strip()

    return (
        "https://raw.githubusercontent.com/"
        + quote(config["owner"], safe="")
        + "/"
        + quote(config["repository"], safe="")
        + "/"
        + quote(raw_ref, safe="")
        + "/"
        + encode_path(pdf_path)
    )


def build_accelerated_url(
    config: dict[str, str],
    raw_url: str,
) -> str:
    """给 GitHub Raw 地址套上下载代理前缀。"""
    proxy = config["download_proxy"].strip()

    if not proxy:
        return raw_url

    return proxy.rstrip("/") + "/" + raw_url


def build_viewer_url(
    pdf_url: str,
    title: str,
    accelerated_url: str,
) -> str:
    """生成优先使用 GHFast、失败后回退本站的阅读器地址。"""
    query = urlencode(
        {
            # 本站地址：加速线路失败时回退
            "file": pdf_url,

            # GHFast 地址：优先用于 PDF.js 预览
            "accelerated": accelerated_url,

            "title": title,

            # 下载按钮继续使用 GHFast
            "download": accelerated_url,
        }
    )

    return f"./viewer.html?{query}"


def render_card(
    pdf: Path,
    pdf_root: Path,
    output_pdf_root: Path,
    cover_root: Path,
    config: dict[str, str],
) -> str:
    """复制 PDF、生成封面并渲染一张画册卡片。"""
    relative = pdf.relative_to(pdf_root)

    # 把原始 PDF 复制到最终 Pages 输出目录。
    target_pdf = output_pdf_root / relative
    target_pdf.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    shutil.copy2(pdf, target_pdf)

    title = pdf.stem.strip() or pdf.name
    category = category_for(
        pdf,
        pdf_root,
        config["uncategorized_name"],
    )
    file_size = format_size(
        pdf.stat().st_size
    )

    # 使用相对路径的哈希作为封面文件名，
    # 避免中文、空格和同名文件造成冲突。
    cover_name = hashlib.sha256(
        str(relative).encode("utf-8")
    ).hexdigest()[:20]

    cover_path = generate_cover(
        pdf,
        cover_root / cover_name,
        title,
    )

    pdf_path = (
        Path(config["pdf_directory"])
        / relative
    )

    # 本站同源 PDF 地址：
    # 供 viewer.html 中的 PDF.js 读取。
    pdf_url = "./" + encode_path(pdf_path)

    cover_url = (
        "./covers/"
        + quote(cover_path.name, safe="")
    )

    raw_url = build_raw_url(
        config,
        pdf_path,
    )

    accelerated_url = build_accelerated_url(
        config,
        raw_url,
    )

    viewer_url = build_viewer_url(
        pdf_url,
        title,
        accelerated_url,
    )

    search_value = " ".join(
        (
            title,
            pdf.name,
            category,
        )
    ).casefold()

    escaped_title = html.escape(title)
    escaped_title_attribute = html.escape(
        title,
        quote=True,
    )
    escaped_category = html.escape(category)
    escaped_size = html.escape(file_size)
    escaped_search = html.escape(
        search_value,
        quote=True,
    )
    escaped_viewer_url = html.escape(
        viewer_url,
        quote=True,
    )
    escaped_download_url = html.escape(
        accelerated_url,
        quote=True,
    )

    return f"""<article class="pdf-card"
         data-search="{escaped_search}">
  <a class="cover-link"
     href="{escaped_viewer_url}"
     target="_blank"
     rel="noopener">
    <img class="cover"
         src="{cover_url}"
         alt="{escaped_title} 首页预览"
         loading="lazy">
  </a>

  <div class="card-body">
    <span class="category">
      {escaped_category}
    </span>

    <h2 class="card-title"
        title="{escaped_title_attribute}">
      {escaped_title}
    </h2>

    <p class="meta">
      {escaped_size}
    </p>

    <div class="actions">
      <a class="button primary"
         href="{escaped_viewer_url}"
         target="_blank"
         rel="noopener">
        在线预览
      </a>

      <a class="button"
         href="{escaped_download_url}"
         target="_blank"
         rel="noopener noreferrer">
        加速下载
      </a>
    </div>
  </div>
</article>"""


def render_page(
    config: dict[str, str],
    cards: list[str],
) -> str:
    """生成画册首页 HTML。"""
    count = len(cards)

    if cards:
        gallery_html = (
            '<main class="gallery" id="gallery">\n'
            + "\n".join(cards)
            + "\n</main>"
        )
    else:
        gallery_html = """<main class="empty">
  <strong>暂时没有 PDF</strong>
  把文件上传到 <code>pdf/</code> 后提交，
  GitHub Actions 会自动生成画册。
</main>"""

    search_script = """
<script>
  const searchInput = document.getElementById("search");
  const cards = Array.from(
    document.querySelectorAll(".pdf-card")
  );
  const resultCount = document.getElementById(
    "result-count"
  );

  function updateGallery() {
    const keyword = searchInput.value
      .trim()
      .toLocaleLowerCase();

    let visible = 0;

    for (const card of cards) {
      const matched =
        !keyword ||
        card.dataset.search.includes(keyword);

      card.hidden = !matched;

      if (matched) {
        visible += 1;
      }
    }

    resultCount.textContent =
      `显示 ${visible} / ${cards.length}`;
  }

  searchInput?.addEventListener(
    "input",
    updateGallery
  );

  updateGallery();
</script>
""" if cards else ""

    title = html.escape(config["title"])
    description = html.escape(
        config["description"]
    )
    owner = quote(
        config["owner"],
        safe="",
    )
    repository = quote(
        config["repository"],
        safe="",
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport"
        content="width=device-width, initial-scale=1.0">
  <meta name="description"
        content="{html.escape(config['description'], quote=True)}">
  <meta name="theme-color"
        content="#1769e0">

  <title>{title}</title>

  <link rel="icon"
        href="./favicon.svg"
        type="image/svg+xml">

  <link rel="stylesheet"
        href="./styles.css">
</head>

<body>
  <div class="page">
    <header class="hero">
      <div class="hero-copy">
        <p class="eyebrow">PDF Gallery</p>

        <h1>{title}</h1>

        <p class="description">
          {description}
        </p>
      </div>

      <a class="repo-link"
         href="https://github.com/{owner}/{repository}"
         target="_blank"
         rel="noopener">
        GitHub 仓库
      </a>
    </header>

    <section class="toolbar"
             aria-label="筛选文档">
      <input class="search"
             id="search"
             type="search"
             placeholder="搜索标题或分类"
             autocomplete="off">

      <span class="result-count"
            id="result-count">
        共 {count} 份
      </span>
    </section>

    {gallery_html}

    <footer class="footer">
      由 GitHub Actions 自动生成 PDF 首页预览
    </footer>
  </div>

  {search_script}
</body>
</html>
"""


def copy_static_files() -> None:
    """复制画册运行所需静态文件。"""
    for filename in STATIC_FILES:
        source = ROOT / filename

        if not source.is_file():
            abort(
                f"缺少必需文件：{filename}"
            )

        shutil.copy2(
            source,
            OUTPUT / filename,
        )


def main() -> None:
    """执行完整构建。"""
    config = load_config()

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)

    OUTPUT.mkdir(parents=True)

    cover_root = OUTPUT / "covers"
    output_pdf_root = (
        OUTPUT / config["pdf_directory"]
    )

    cover_root.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_pdf_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    copy_static_files()

    pdf_root = (
        ROOT / config["pdf_directory"]
    )
    pdfs = find_pdfs(pdf_root)

    cards = [
        render_card(
            pdf=pdf,
            pdf_root=pdf_root,
            output_pdf_root=output_pdf_root,
            cover_root=cover_root,
            config=config,
        )
        for pdf in pdfs
    ]

    index_html = render_page(
        config,
        cards,
    )

    (OUTPUT / "index.html").write_text(
        index_html,
        encoding="utf-8",
    )

    # GitHub Pages 请求不存在路径时仍显示站点外壳。
    (OUTPUT / "404.html").write_text(
        index_html,
        encoding="utf-8",
    )

    (OUTPUT / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n",
        encoding="utf-8",
    )

    print(
        f"Built gallery with {len(pdfs)} PDF file(s)."
    )
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()