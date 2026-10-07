# CapCut 日本区舞蹈模板创作者审核工具

自动发现 CapCut 日本区、非 AI、舞蹈模板创作者，并提供本地网页进行人工审核、审美学习和导出。程序不调用 OpenAI，也不写入飞书。

## 快速开始

需要 **Python 3.9+**（只用标准库，无需 `pip install`）。

| 系统 | 启动 | 停止 |
| --- | --- | --- |
| Windows | 在 Git Bash 中运行 `./run.sh`（或双击，若 `.sh` 已关联 Git Bash） | `./stop.sh` |
| macOS | 双击 `run.command` | 双击 `stop.command` |

启动脚本会在后台运行两个服务，然后自动打开浏览器：

- 前端页面：<http://127.0.0.1:5173/>
- 后端 API：<http://127.0.0.1:8765/api/health>

服务在后台运行，启动窗口可以关闭；日志和进程号保存在 `.run/`。端口可用环境变量 `BACKEND_PORT`、`FRONTEND_PORT` 修改（改后端端口时同步修改 `frontend/js/config.js`）。

**第一次启动**会自动创建 SQLite 数据库 `backend/data/capcut.db`，并把旧版 JSON 数据（`backend/data/legacy/`，以及旧版遗留在 `capcut_local_data/` 下的模板缓存、视频分析缓存）一次性导入。之后所有数据都只保存在数据库中。数据库不纳入 Git，换电脑时请复制 `backend/data/capcut.db`。

## 目录结构

```
run.sh / stop.sh             Windows（Git Bash）启动 / 停止，macOS/Linux 也可用
run.command / stop.command   macOS 双击启动 / 停止（调用 run.sh / stop.sh）
backend/                     后端：Python 标准库 HTTP JSON API + SQLite
  main.py                    入口：启动 API、命令行扫描、批量核验主页
  app/
    config.py                路径、端口、规则常量、专题入口列表
    db.py                    表结构、连接
    repository.py            表 <-> 字典 的读写
    capcut.py                访问 CapCut 页面 / CapCut 接口 / Oricon 榜单（只取数，不碰数据库）
    discovery.py             扫描流程：专题页 → 模板 → 作者筛选 → 评分 → 生成审核批次
    scoring.py               匹配度：正面案例审美 70% + 数据质量 30% + 审核反馈修正
    learning.py              审美学习：审核反馈词、手动调权、负面视频样本
    video.py                 本地视频分析（Apple Vision，仅 macOS）
    reviews.py               审核保存与校验、审核列表、CSV 导出、排除名单
    category.py              新类别工作区（只学正面案例）
    jobs.py                  页面触发的后台刷新任务
    api.py                   路由与 HTTP 处理
    legacy_import.py         旧版 JSON 一次性导入
  resources/                 正面案例、种子模板、视频分析 Swift 源码
  data/                      数据库（不入 Git）和旧版 JSON 快照 legacy/
  tests/                     单元测试
frontend/                    前端：纯静态 HTML/CSS/JS，无构建步骤
  index.html                 创作者审核
  aesthetic.html             舞蹈审美机制
  new-category.html          新类别工作区
  js/config.js               后端地址
  serve.py                   静态文件服务
docs/                        审美标准、首批筛选结果、项目状态
scripts/install_daily_scan.command   macOS：安装每天 9:00 自动扫描
```

## 架构

最简单的前后端分离：

- **前端**是静态页面，由 `frontend/serve.py` 提供，通过 `fetch` 调用后端 JSON API。
- **后端**是一个 Python 进程：`ThreadingHTTPServer` 处理 API，扫描在后台线程执行；数据存在单个 SQLite 文件。
- 后端只允许来自前端地址（`127.0.0.1:5173` / `localhost:5173`）的跨域请求，并且只监听本机。

### 数据表

| 表 | 内容 |
| --- | --- |
| `creators` | 作者：身份、主页资料、统计、得分、是否在审核队列（`in_queue`）、推荐类型 |
| `templates` | 扫描到的所有模板，按 `creator_key` 归属作者；7 天 / 1000 uses 规则在读取时实时计算 |
| `reviews` | 人工审核结论（待审 / 通过 / 审美达标·数据不足 / 排除）和填写的信息 |
| `term_overrides` | 审美规则的手动调权；`weight` 为空表示删除该词 |
| `preference_edits` | 审美规则修改记录 |
| `rejected_visual_profiles` | 排除作者的视频特征，作为负面视觉样本 |
| `video_analyses` | 单条模板视频的分析缓存 |
| `template_cache` | 模板详情页缓存（12 小时） |
| `seen_live_templates` | 实时专题页出现过的模板，用于统计“首次索引” |
| `scans` | 每次扫描的结果与统计 |
| `exclusions` | 已归类作者排除名单 |
| `category_cases` | 新类别工作区的正面案例 |
| `settings` | 少量单值状态：扫描页游标、热歌缓存、审美档案版本 |

审美偏好（加分 / 扣分词）不单独存储，每次由 `reviews` 推导，再叠加 `term_overrides`。

### API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/overview` | 各状态人数、最近一次扫描摘要 |
| GET | `/api/creators?view=pending\|approved\|aesthetic_only\|rejected\|all` | 审核队列 |
| POST | `/api/reviews` | 保存审核结论 |
| POST | `/api/profiles/resolve` | 从主页分享链接读取 CC ID、投稿数、TT 链接 |
| GET | `/api/export/approved.csv` | 下载已通过作者表格 |
| GET / POST | `/api/refresh` | 刷新状态 / 开始手动刷新 |
| POST | `/api/refresh/cancel` | 停止刷新 |
| GET | `/api/aesthetic` | 审美学习档案 |
| PUT | `/api/aesthetic/terms` | 修改加分 / 扣分规则并重新计算匹配度 |
| GET | `/api/categories/new` | 新类别工作区状态 |
| POST | `/api/categories/new/cases` | 导入正面案例 |
| GET / PUT | `/api/exclusions` | 读取 / 替换排除名单 |

## 使用说明

**审核**：点击视频预览播放或暂停。作者主页分享链接粘贴到审核栏后，点“从主页链接读取”会填写 CC ID 和主页投稿总数。“通过”需要确认非 AI、舞蹈质量，并填写 CC ID 或主页链接、舞蹈类型和包装节奏评价；“排除”必须填写不通过原因，原文会成为反向提示词。“审美达标·数据不足”保存为正向审美反馈，但不进入导出表格。

**匹配度**：读取 26 条正面案例，审美匹配占 70%，数据质量占 30%，再叠加审核反馈修正（每点正向权重 +2，反向 -4，总修正限制在 ±30）。在“舞蹈审美机制”页可直接修改加分 / 扣分词。

**刷新**：“手动刷新候选”读取 CapCut 舞蹈专题和日本 TikTok 热歌专题第 1–3 页的实时列表，整批替换待审作者（最多 50 位：匹配分最高的 30 位 + 其余合格作者中随机 20 位）。被替换的未审核作者以后仍可能出现；只有人工“排除”的作者会被永久跳过。没有首次索引的新模板或没有合格作者时，保留原候选并提示原因。

**硬性规则**：发布满 7 天且 uses 小于 1000 的模板直接排除；作者需有日文信号和至少一条非 AI 舞蹈模板。主页投稿数和 ≥3000 uses 的作品数只用于排序。

**排除名单**：审核页的“已归类作者排除名单”中粘贴飞书里已归类作者的 CC 名称或 ID，每行一个。

**视频分析**：macOS 上会用 Apple Vision 分析排名靠前作者的模板视频，与排除作者的视频特征比较后扣分；Windows 上自动跳过这一步，只用标题和描述判断。

**命令行**：

```bash
python backend/main.py --scan-only            # 执行一次增量扫描后退出（定时任务使用）
python backend/main.py --check-profiles URL…  # 批量核验作者主页分享链接
python -m unittest discover -s backend/tests  # 运行测试
```

macOS 每日自动扫描：双击 `scripts/install_daily_scan.command`（先实际测试一次扫描，成功后才安装）。
