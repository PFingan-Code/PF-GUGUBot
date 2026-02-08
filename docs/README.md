# GUGUBot 文档

本目录包含 GUGUBot 的完整文档。

## 本地预览

### 安装依赖

```bash
pip install -r requirements-docs.txt
```

### 启动本地服务器

```bash
mkdocs serve
```

然后在浏览器访问 `http://127.0.0.1:8000`

### 构建静态网站

```bash
mkdocs build
```

生成的网站将位于 `site/` 目录。

## 在线文档

访问 [https://pfingan-code.github.io/PF-GUGUBot/](https://pfingan-code.github.io/PF-GUGUBot/) 查看在线文档。

## 文档结构

- `index.md` - 首页
- `installation.md` - 安装指南
- `configuration.md` - 配置说明
- `features.md` - 功能详解
- `multi-server.md` - 多服互联教程
- `api.md` - API 文档
- `troubleshooting.md` - 疑难解答

## 贡献文档

欢迎改进文档！提交 PR 前请确保：

1. 文档格式正确（使用 Markdown）
2. 链接有效
3. 代码示例正确
4. 本地预览无误

## 自动部署

文档会通过 GitHub Actions 自动部署到 GitHub Pages：

- 推送到 `main` 或 `2.0.0` 分支时
- 修改 `docs/` 目录下的文件时
- 修改 `mkdocs.yml` 时

部署配置见 `.github/workflows/docs.yml`

