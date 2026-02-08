# 文档说明

本项目已配置完整的文档系统，使用 MkDocs Material 主题。

## 📚 查看在线文档

访问：[https://pfingan-code.github.io/PF-GUGUBot/](https://pfingan-code.github.io/PF-GUGUBot/)

## 🚀 本地预览文档

### 1. 安装依赖

```bash
pip install -r requirements-docs.txt
```

### 2. 启动本地服务器

```bash
mkdocs serve
```

### 3. 访问

在浏览器中打开：`http://127.0.0.1:8000`

文档会自动热重载，修改后刷新即可看到变化。

## 📝 文档结构

```
docs/
├── index.md              # 首页 - 项目介绍和导航
├── installation.md       # 安装指南 - 详细的安装步骤
├── configuration.md      # 配置说明 - 完整的配置选项
├── features.md           # 功能详解 - 所有功能的使用方法
├── multi-server.md       # 多服互联 - 多服务器配置教程
├── api.md                # API 文档 - 开发者接口文档
├── troubleshooting.md    # 疑难解答 - 常见问题和解决方案
└── README.md             # 文档说明
```

## 🔧 文档配置

- **mkdocs.yml** - MkDocs 配置文件，包含主题、插件、导航等设置
- **requirements-docs.txt** - 文档构建所需的 Python 依赖
- **.github/workflows/docs.yml** - GitHub Actions 自动部署配置

## 🤖 自动部署

文档会在以下情况自动部署到 GitHub Pages：

- 推送到 `main` 或 `2.0.0` 分支
- 修改 `docs/` 目录下的文件
- 修改 `mkdocs.yml` 配置文件

部署过程：
1. GitHub Actions 检测到代码推送
2. 安装 Python 和依赖
3. 运行 `mkdocs gh-deploy`
4. 将生成的静态网站推送到 `gh-pages` 分支
5. GitHub Pages 自动发布

## 📋 手动部署

如果需要手动部署：

```bash
# 构建文档
mkdocs build

# 部署到 GitHub Pages
mkdocs gh-deploy
```

## ✏️ 编辑文档

### 编辑现有页面

直接编辑 `docs/` 目录下的 `.md` 文件即可。

### 添加新页面

1. 在 `docs/` 目录创建新的 `.md` 文件
2. 在 `mkdocs.yml` 的 `nav` 部分添加导航项：

```yaml
nav:
  - 新页面: new-page.md
```

### Markdown 语法

文档支持以下扩展语法：

#### 代码块

````markdown
```python
def hello():
    print("Hello, World!")
```
````

#### 警告框

```markdown
!!! note "提示"
    这是一个提示信息

!!! warning "警告"
    这是一个警告信息

!!! danger "危险"
    这是一个危险警告
```

#### 标签页

```markdown
=== "Python"
    ```python
    print("Hello")
    ```

=== "JavaScript"
    ```javascript
    console.log("Hello")
    ```
```

#### 任务列表

```markdown
- [x] 已完成的任务
- [ ] 未完成的任务
```

## 🎨 主题自定义

如需自定义主题，编辑 `mkdocs.yml`：

### 修改配色

```yaml
theme:
  palette:
    primary: indigo    # 主色调
    accent: indigo     # 强调色
```

可选颜色：`red`, `pink`, `purple`, `deep purple`, `indigo`, `blue`, `light blue`, `cyan`, `teal`, `green`, `light green`, `lime`, `yellow`, `amber`, `orange`, `deep orange`

### 修改图标

```yaml
theme:
  icon:
    logo: material/robot  # 网站图标
```

更多图标见：[Material Icons](https://squidfunk.github.io/mkdocs-material/reference/icons-emojis/)

## 📖 参考资料

- [MkDocs 官方文档](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [Markdown 语法指南](https://markdown.com.cn/)

## ❓ 常见问题

### 文档构建失败

**问题**：`mkdocs serve` 或 `mkdocs build` 报错

**解决**：
1. 检查 Python 版本 ≥ 3.8
2. 重新安装依赖：`pip install -r requirements-docs.txt`
3. 检查 `mkdocs.yml` 语法是否正确

### 图片不显示

**问题**：文档中的图片无法显示

**解决**：
1. 将图片放在 `docs/images/` 目录
2. 使用相对路径引用：`![描述](images/pic.png)`

### 中文搜索不工作

**问题**：搜索中文内容没有结果

**解决**：
在 `mkdocs.yml` 确认已配置中文搜索：

```yaml
plugins:
  - search:
      lang:
        - zh
        - en
```

## 💡 提示

1. **使用热重载**：`mkdocs serve` 会自动检测文件变化并刷新
2. **检查链接**：使用 `mkdocs build --strict` 检查断链
3. **预览部署**：推送前本地运行 `mkdocs build` 确保无误
4. **版本管理**：使用 Git 追踪文档变更

---

**需要帮助？**

- QQ 交流群：[726741344](https://qm.qq.com/q/TqmRHmTmcU)
- GitHub Issues：[提交问题](https://github.com/PFingan-Code/PF-GUGUBot/issues)

