# LocalLeaf — 本地离线论文编辑器

采用类似 Overleaf 的文件 / LaTeX 源码 / PDF 三栏布局。文件、编辑器资源、字体和编译器都保存在本机。服务只监听 `127.0.0.1`，无需账号、云端服务或在线 CDN。

## 开始使用

1. 在 Finder 中打开此文件夹，双击 **LocalLeaf.app**（或 **启动 LocalLeaf.command**）。使用 App 时服务会在后台运行，不会打开终端窗口。
2. 浏览器会打开 [本地工作台](http://127.0.0.1:8787)。保持启动时的终端窗口运行。
3. 编辑 `main.tex`，按 **⌘Enter** 编译；停止输入 650 毫秒后自动保存，**⌘S** 立即保存。
4. 点击顶部项目名称，可创建中文 / 英文项目，或导入从 Overleaf 下载的项目 ZIP。
5. 使用完毕后先等待「所有更改已保存」，再在启动终端按 **Ctrl+C** 停止服务。

本次已将 TinyTeX 编译器及中文 CTeX / Fandol 字体安装到 `runtime/TinyTeX/`，在本机可直接离线运行。初次准备时下载依赖；启动、编辑、保存和已安装宏包的编译过程均不需要联网。

也可用终端启动：

```sh
cd /Users/sz5380/Phd/Software/localleaf
python3 server.py
```

端口被其他程序占用时：`python3 server.py --port 8788`。

## 已有功能

- 多项目、文件夹路径、新建 / 上传 / 重命名 / 删除文件，图片和 PDF 附件预览。
- 本地 CodeMirror 编辑器：LaTeX 语法高亮、行号、撤销重做、章节大纲、查找替换、公式 / 引用片段、字号和分屏宽度调整。
- 自动保存；关闭页面时提示未保存内容；同一浏览器、同一地址重新打开时可恢复缓存草稿。
- 按文件内容摘要检测并发修改，发生冲突时拒绝覆盖；可在文件操作菜单下载当前编辑副本。
- 每个项目保留最近 200 次修改前的文件内容。删除也保留可恢复版本。历史记录是本地辅助功能，请定期自行备份重要论文。
- XeLaTeX / pdfLaTeX / LuaLaTeX；latexmk 处理多轮编译、交叉引用和 BibTeX / Biber。
- 手动 / 自动编译、真实 PDF 预览与下载、编译日志、ZIP 导入导出。
- PDF 与源码反向定位：双击 PDF 正文可打开对应项目文件并跳转到相关 LaTeX 行。
- 一键与 Overleaf Git 项目同步；令牌保存在 macOS 钥匙串，不写入论文目录。
- 项目文件夹直接使用项目名称；同名项目追加 `(2)` 序号。
- 编译使用项目快照；失败时保留上次成功的 PDF；单次编译 120 秒后超时停止。

## 从 Overleaf 迁移

在 Overleaf 下载源文件 ZIP。在 LocalLeaf 顶部项目菜单选择「导入 ZIP」，然后到设置确认主 `.tex` 文件和编译器。中文请选择 XeLaTeX。

ZIP 最多 2000 个文件、解压总计 80 MB；单文件最多 20 MB。隐藏配置文件会跳过，项目中的 `.latexmkrc` 不执行。重命名文件后需自行调整 LaTeX 引用路径。

宏包与字体取决于具体模板。自带分发涵盖常见写作包与中英文模板，但不等于完整 TeX Live。某个期刊模板如果使用尚未安装的包，需要在有网时事先安装，再确认断网也能编译：

```sh
"$PWD/runtime/TinyTeX/bin/universal-darwin/tlmgr" install 宏包名
```

以上命令请在 LocalLeaf 文件夹内执行。特殊脚本、`minted` 等需要 shell escape 的项目不受支持，建议改用 `listings`。

## Overleaf Git 同步

Overleaf Git 是 Overleaf 的高级功能。进入在线项目的“集成 → Git”，复制 Git 地址；再到 Overleaf 账户设置生成 Git authentication token。LocalLeaf 顶部点击“连接 Overleaf”，首次可选择采用 Overleaf 最新版本，或保留本地版本并上传。之后“同步 Overleaf”会自动识别远端的 `main` 或 `master` 分支，先拉取、提交本地修改再推送。用户名固定为 `git`，令牌由 macOS 钥匙串保存。

## 文件与备份

`projects/<项目名称>/` 里直接存放 `.tex`、`.bib`、图片等原始文件，可以用其他编辑器打开。`.localleaf.json` 保存项目设置；`.history/` 保存版本；`.build/output.pdf` 是最后成功编译的 PDF。

「导出项目」生成可再次上传到 Overleaf 的源码 ZIP，不包含本地历史版本和 PDF。要完整备份项目设置与历史，请复制整个 `projects/` 文件夹。不要在编译时同时用外部工具修改同一项目。

编译器与本地依赖放在 `runtime/` 和 `static/vendor/`。当前安装的是 macOS universal 版本。复制到另一台 Mac 时，需要该机具备 Python 3；Windows / Linux 需要另外安装相应平台的 TeX Live，然后用 `python3 server.py` 启动。所有前端静态资源均已随项目保存。

## 验证

```sh
python3 -B -m unittest discover -s tests -v
```

测试使用临时项目目录，不修改论文。覆盖保存冲突、版本恢复、路径与 ZIP 校验、项目导出、编译失败保留 PDF、中英文编译及参考文献。HTTP 测试需要允许本机监听。

## 来源与许可

LocalLeaf 为独立实现，与 Overleaf 无隶属关系。交互布局参考 [Overleaf 编辑器布局说明](https://docs.overleaf.com/navigating-in-the-editor/working-with-the-pdf-viewer/editor-and-pdf-layout-and-sizing)。

- [CodeMirror 5.65.16](https://github.com/codemirror/codemirror5/tree/5.65.16)：MIT，许可保留于 `static/vendor/LICENSE`。
- [TinyTeX 2026.09](https://github.com/rstudio/tinytex-releases/releases/tag/v2026.09)：基于 TeX Live；分发内各组件遵循各自许可证，见 `runtime/TinyTeX/LICENSE.TL` 和各宏包许可。
- [TinyTeX 官方文档](https://yihui.org/tinytex/)。

## 启动栏图标

可将 `LocalLeaf.app` 从 Finder 拖到 Tab Launcher 的普通自定义标签中。此入口带有绿色书页图标；应用本体请保留在本文件夹内。它会通过终端启动现有脚本。已验证应用包结构、图标文件和本地签名，未在 Tab Launcher 内实际操作验证。
