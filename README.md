# 红利股票配置计算

一个本地运行的**个人投资仪表盘**：把「红利股票配置计算模板」做成网页版，接入实时行情，用于记录净资产、股票/基金持仓、预计分红，并做目标测算与动态选股。

- **零第三方依赖**：后端只用 Python 标准库（http.server / sqlite3 / urllib），前端只用原生 HTML / CSS / JS。
- **本地优先**：所有数据存本机 SQLite，不依赖外部账号（AI 建议为可选功能）。

## 功能

- **储蓄计划**（默认页）
  - 顺序：总览 → 当前资产快照 → 持仓 → 目标与进度 → 净资产趋势 → 历史明细（默认收起）→ AI 建议
  - 净资产与周 / 月 / 季 / 年趋势（红 = 上升、绿 = 下降）
  - 股票实仓：实时价、股息率、预计年分红
  - 基金实仓：场外净值（带净值日期）、ETF 盘中价、货基 7 日年化，主指标为近 1 年涨幅
  - 目标进度 + 按实际趋势预测 + 0% / 4% / 6% / 8% 四档情景
  - AI 建议：OpenAI 兼容接口（DeepSeek / OpenAI / 自定义），纪律条款可编辑
- **动态选股**：每日缓存全 A 股行情与近 3 年分红，高股息低价初筛 + 规则二次筛选 + 优中选优评分，可一键加入实仓
- 颜色约定：红 = 上升、绿 = 下降、橙 = 需关注

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3（仅标准库） |
| 前端 | 原生 HTML / CSS / JS，无框架，手写 SVG 图表 |
| 存储 | SQLite（`data/app.db`） |

## 快速开始

### Windows

```bash
python server.py --open     # 前台运行并自动打开浏览器
```

或双击根目录 `启动网站.bat`；如需后台常驻（登录自启 + 失败重启），用 `scripts\` 下的 `install_service.bat` 等脚本。

### Linux（Ubuntu）

```bash
cd 项目目录
python3 server.py --host 0.0.0.0 --port 8000 --service
```

systemd 用户服务（开机自启）示例：

```ini
# ~/.config/systemd/user/dividend-app.service
[Unit]
Description=红利股票配置计算服务
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/project
ExecStart=/usr/bin/python3 server.py --host 0.0.0.0 --port 8000 --service
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now dividend-app.service
sudo loginctl enable-linger "$USER"   # 开机自启（未登录也运行）
```

访问 `http://127.0.0.1:8000`；局域网其他设备用 `http://<主机IP>:8000`。

## 目录结构

```
├── app/                 # 后端（Python 标准库）
│   ├── server.py        # HTTP 服务 + API 路由
│   ├── store.py         # SQLite 持久化
│   ├── market.py        # 股票行情 / 分红
│   ├── fund.py          # 基金搜索 / 净值 / ETF / 货基
│   ├── trend.py         # 周/月/季/年趋势（只读 SQLite）
│   ├── stock_screener.py# 动态选股（每日缓存）
│   └── run.py           # 入口
├── web/                 # 前端（静态资源）
│   ├── index.html
│   ├── css/style.css
│   └── js/              # app / savings / funds / advice / screener / common
├── data/                # 运行数据（不入库，见「数据与隐私」）
├── scripts/             # Windows 服务管理脚本（仅 Windows 用）
├── docs/README.md       # 详细使用说明
├── server.py            # 兼容入口：python server.py
└── 启动网站.bat          # Windows 双击即用
```

## 数据与隐私

`data/` 目录**不纳入版本库**（见 `.gitignore`），包含：

- `data/app.db`：个人财务数据（股票 / 基金 / 资产快照 / AI 建议缓存）
- `data/ai_config.json`：AI 服务地址 / 模型 / API Key
- `data/backups/`：数据库备份

首次运行会自动创建 `data/`。如需从旧数据导入，把 `stocks.json` 或 Excel 模板放入 `data/` 即可；页面上的增删改会直接写入 SQLite。

### AI 配置

优先级：环境变量 > `data/ai_config.json` > 默认值。

- 环境变量：`AI_BASE_URL` / `AI_MODEL` / `AI_API_KEY`（或 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`）
- 也可以在页面「AI 设置」里填写，Key 只保存在本机，不回显。

## 更详细文档

功能说明、扩展方式、数据来源等见 [docs/README.md](docs/README.md)。

## 免责声明

本工具仅用于配置计算参考，不构成任何投资建议；实际分红以上市公司公告为准，投资有风险。
