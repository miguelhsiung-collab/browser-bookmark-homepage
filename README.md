# browser-bookmark-homepage

从 Chrome、Edge、Brave、Perplexity Comet 等 Chromium 内核浏览器的书签和历史记录，生成可本地打开的导航主页。默认视觉风格接近 littleheli / OneNav。也支持在主页上隐藏卡片（不影响浏览器书签），以及定时自动更新「高频访问」。

不适用于：只处理 Firefox、编写浏览器扩展，或部署自建 OneNav 服务。

## 安装

```bash
npx -y skills add miguelhsiung-collab/browser-bookmark-homepage -g --all
```

## 使用

安装后，可以这样开始：

> 使用 $browser-bookmark-homepage 完成它所解决的任务，并按可观察标准检查结果。

生成主页后：

- 悬停或点「编辑主页」可从本页移除卡片；「已删除」里可恢复。这不会删除浏览器书签。
- 运行 `scripts/update_frequent.py --watch --serve --interval 15`（Windows 也可用 `scripts/watch_frequent.bat` 或 `scripts/install_scheduled_task.bat`），即可自动刷新高频访问。说明见 Skill 内 `references/delete-and-auto-update.md`。

## 运行依赖

- 支持 Agent Skills 的客户端
- Python 3（用于运行 Skill 内脚本；自动更新也需要在本机安装 Python 3）

## 内容

本仓库只发布运行这个 Skill 所需的文件。本地评测样本、预期答案和运行记录不包含在公开包中。请勿把个人书签或 History 数据库推送到本仓库。
