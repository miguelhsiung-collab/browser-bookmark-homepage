# 删除卡片与高频访问自动更新

这两项都只影响导航主页，不会改浏览器里的书签或历史记录。

## 从主页删除卡片

- 鼠标悬停卡片右上角会出现 ×；也可以点「编辑主页」，让所有卡片都显示 ×。
- 点 × 后，卡片从本页消失，并出现「撤销」提示。
- 「已删除」面板可以逐条或全部恢复。
- 删除记录保存在浏览器的 `localStorage`，以及主页旁边的 `hidden.json`（需本地服务正在运行时才能自动写文件）。用 `file://` 打开时，可在「已删除」面板点「导出 hidden.json」，把文件放到主页同一目录，之后的自动更新就会继续尊重这份名单。
- 从「高频访问」移除的站点按域名记住，刷新 Top 20 时不会再出现，空出的名额由下一个站点补上。
- 从普通书签分类移除时，只隐藏该网址，不影响浏览器书签本身。

## 高频访问自动更新

静态 HTML 自己读不了 Chrome / Comet 的 History 数据库。需要运行 Skill 里的 `scripts/update_frequent.py`：

1. 先把 History 复制出来再查询（浏览器开着时数据库通常是锁住的）。
2. 按域名汇总访问次数，套用 `host-filters.md` 的登录/认证过滤。
3. 尊重 `hidden.json` 删除名单，重新计算 Top 20。
4. 原地补丁主页里的 `<!--NAV_FREQUENT_START-->` 数据块，并写入旁边的 `frequent-data.js`。

### 推荐：本地服务（更顺畅）

在已填写好的配置下运行：

```bash
python scripts/update_frequent.py --config scripts/updater-config.json --watch --serve --interval 15
```

Windows 也可双击 `scripts/watch_frequent.bat`，或运行 `scripts/install_scheduled_task.bat` 做成登录时自动启动。

- 服务只监听 `127.0.0.1`（默认 8765），不对外网开放，也不列出主页目录里的其他文件。
- 用 `http://127.0.0.1:8765/` 打开主页最顺畅；即便仍用 `file://` 打开，页面也会尝试向本地服务拉取 `/api/frequent`，并在焦点回到页面或大约每 15 分钟时原地刷新高频区块（编辑或「已删除」面板打开时会跳过）。
- 删除 / 恢复会通过 `/api/hidden` 写回 `hidden.json`。

### 只用 file:// + 定时更新

没有本地服务时：

- 定时任务或不带 `--serve` 的 `--watch` 仍会改写 HTML 和 `frequent-data.js`。
- 已打开的 `file://` 标签页会尝试重新加载旁边的 `frequent-data.js`；若浏览器缓存导致读不到新数据，重新打开该 HTML 即可看到最新高频访问。
- 删除记录以 `localStorage` 为准。若希望更新脚本也给隐藏站点让出 Top 20 名额，把 `hidden.json` 放在主页旁边。

### 配置项

`scripts/updater-config.example.json` 可复制为 `updater-config.json`。常用字段：

- `homepage`：一个或多个 HTML 路径（例如桌面和 OneDrive 各一份）
- `browser`：`comet` / `chrome` / `edge` / `brave`
- `profile`：默认 `Default`
- `interval`：分钟，默认 15
- `port`：默认 8765
- `top`：展示条数，默认 20

Windows 若未安装 Python 3，自动更新无法在本地运行，应向用户说明，并改由 Agent 定期在用户电脑上执行一次更新脚本（可能需要用户批准机器命令）。
