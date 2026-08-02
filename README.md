# test.github.io PDF 画册

一个无侧边栏、无 Docsify 的纯静态 PDF 画册模板。

## 页面效果

- PDF 首页缩略图；
- 响应式画册网格；
- 标题与分类搜索；
- 在线打开与下载；
- `pdf/` 子文件夹自动成为分类；
- GitHub Actions 自动构建和部署。

## 部署

1. 把仓库文件提交到 `test.github.io` 的 `main` 分支。
2. 进入 **Settings → Pages**。
3. 将 **Source** 设置为 **GitHub Actions**。
4. 把 PDF 上传到 `pdf/`。
5. 查看 **Actions → Deploy PDF Gallery**。

## 修改站点信息

编辑 `site-config.json`。

## 本地构建

需要安装 Poppler 才能生成 PDF 首页缩略图：

```bash
python3 scripts/build_site.py
```

如果本地没有 `pdftoppm`，构建脚本会自动使用占位封面；GitHub Actions 中会安装 Poppler。
