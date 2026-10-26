# CapCut 创作者雷达 v3

上传一类视频 → 系统学会这种模板风格 → 自动去 CapCut 检索、排序会做这类模板的创作者 → 人工审核，审核结果继续反哺学习。

- **多类别**：舞蹈之外可以随时新建类别（旅行 vlog、卡点变装……），每个类别独立学习、独立审核。
- **模板基因**：每个视频在本机提取卡点同步度、切镜节奏、色调、包装、版式、人物构图等 26 项特征 + 14 格色调分布。
- **像 Midjourney 一样越点越准**：“风格训练”页每次展示一组模板，点选喜欢的即可；每轮更新模型并生成新的风格档案编号（如 `danc-v12-3f9a2c`）。
- **可解释**：每个类别都能看到学到了什么（“偏好：画面变化更贴合音乐重拍；避开：分屏拼贴…”），每条作品显示风格匹配分和原因。
- **不调用任何外部 AI 服务**，所有视频分析在本机完成。

方法说明见 [docs/模板学习方法.md](docs/模板学习方法.md)，调研见 [docs/research/视频模板自学习_调研.md](docs/research/视频模板自学习_调研.md)，给客户的上传说明见 [docs/客户素材上传指南.md](docs/客户素材上传指南.md)。

## 快速开始（Mac）

1. 双击 **安装依赖.command**（只需一次）：创建 `.venv`，安装 numpy / OpenCV / ffmpeg 等，并自动做一次网络检查。
2. 双击 **打开审核.command**，浏览器打开 <http://127.0.0.1:8765/>。
3. 可选：双击 **安装每日扫描.command**，每天 9:00 自动扫描所有类别。

### 从 v2 升级（已在用旧版的 Mac）

旧版的数据（`capcut_local_data/*.json`）会被自动迁移到 `capcut_local_data/categories/dance/`，审核记录、已见作者、反向提示词全部保留，排序分数与 v2 一致。
如果 Mac 上的旧数据比仓库里的更新（例如一直在跑每日扫描），按下面做，程序会自动以**更新的那份**为准，并把被替换的文件备份到 `categories/dance/before-v3-migration-*/`：

```bash
cp -R capcut_local_data ~/Desktop/capcut_v2_backup     # 先备份
git stash -u                                            # 暂存本地数据改动，避免拉取冲突
git pull                                                # 或 git checkout 本分支
cp ~/Desktop/capcut_v2_backup/*.json capcut_local_data/ # 把旧版 json 放回数据根目录
./打开审核.command                                       # 启动时自动迁移
```

## 使用流程

1. **首页**选择类别，或新建类别（名称 + CapCut 搜索关键词）。
2. **示例与设置**：拖入示例视频，或粘贴 CapCut 模板链接 / Google Drive / Dropbox / zip 链接 / 本机文件夹路径。勾选“按子文件夹名自动分到不同类别”可一次导入客户的整个素材库（子文件夹名 = 类别，`反例` 子文件夹 = 反例）。
3. **风格训练**：每组点选“像这个类别、做得好”的模板（数字键选择，Shift+数字 标记“完全不像”，回车提交）。候选太少时点“分析更多候选视频”。
4. **审核作者**：点“扫描新作者”。每位作者显示综合分 / 审美 / 视频风格 / 数据分，每条作品显示风格匹配度（绿 ≥70，黄 ≥45，红 <45）和原因。粘贴作者主页分享链接可自动读取 CC ID、投稿数，并在后台拉取该作者**全部模板**核查类别占比。
5. 通过 / 审美达标·数据不足 / 排除（必须写原因）。备注会变成文字规则，排除作者的视频会成为风格反例。
6. **风格档案**：查看学到的偏好、代表案例、版本记录；编辑文字规则。
7. 顶部“下载已通过表格”导出 CSV（字段与 v2 相同，另加类别、风格档案编号、综合分）。

## 命令行

```bash
.venv/bin/python capcut_local.py                       # 打开网页（同 打开审核.command）
.venv/bin/python capcut_local.py doctor                # 检查网络与依赖，逐个域名给出原因和修复方法
.venv/bin/python capcut_local.py new "旅行vlog" --keywords "旅行,vlog,旅行動画"
.venv/bin/python capcut_local.py ingest ~/Downloads/客户素材.zip --by-folder
.venv/bin/python capcut_local.py ingest "https://www.dropbox.com/scl/fo/..." --by-folder
.venv/bin/python capcut_local.py ingest links.txt --category dance
.venv/bin/python capcut_local.py analyze --category dance --limit 80   # 预先分析候选视频
.venv/bin/python capcut_local.py train --category dance               # 重新训练并重排
.venv/bin/python capcut_local.py scan --category all                  # 扫描（每日任务使用 --refresh --scan-only）
.venv/bin/python -m pytest -q                                          # 测试
```

## 网络（“无法连接 CapCut”）

运行 `doctor`（或网页右上角“网络检查”）会逐个测试以下域名并说明失败原因（DNS 无法解析 / 代理拒绝 / 证书 / 超时）：

| 域名 | 用途 | 必需 |
|---|---|---|
| `www.capcut.com` | 模板详情页、专题页、相关推荐 | 是 |
| `feed-api.capcutapi.com` | 作者主页信息与全部模板 | 是 |
| `mobile.capcutshare.com` | 主页 / 模板分享短链 | 是 |
| `*.capcutvod.com`（如 `v16-vod.capcutvod.com`） | 预览视频（风格分析） | 是 |
| `*.ibyteimg.com` | 封面图 | 否 |
| `www.oricon.co.jp` | 日本 TikTok 周榜（舞蹈热歌入口） | 否 |
| `www.dropbox.com`、`*.dropboxusercontent.com`、`drive.google.com`、`drive.usercontent.google.com` | 导入客户素材 | 导入时需要 |
| `huggingface.co` | 仅可选的 CLIP 模型下载 | 否 |

- **在自己的 Mac 上**：中国大陆网络需要能访问 CapCut 的 VPN；python.org 安装的 Python 若报证书错误，`安装依赖.command` 已安装 `certifi` 解决。
- **在 Claude Code 云端环境里**：默认网络策略只允许包管理器等少数域名，CapCut 会被拒绝（`doctor` 显示 `proxy_blocked`）。在云端环境设置 → Network access 中把上表域名加入 Allowed domains（或选择更宽的访问级别）即可，详见 <https://code.claude.com/docs/en/cloud-environments#network-access>。
- 网络不通时程序不会丢数据：扫描失败会保留上次结果，已缓存的模板页仍可使用。

## 目录

```
capcreator/            程序包
  capcut.py            CapCut 网页/接口/分享链接
  net.py  doctor.py    网络层（重试、证书、错误分类）与自检
  dna.py               模板基因提取（OpenCV + ffmpeg）
  embed.py             可选 CLIP 语义向量
  taste.py             风格学习模型（示例 + 点选 + 审核 → 档案）
  learn.py scoring.py  训练数据组装、作者打分
  discovery.py         CapCut 相关推荐图谱扫描与合并
  ingest.py            示例导入（文件夹/zip/网盘/模板链接）
  category.py          类别与数据存储、v2 迁移
  server.py web/       本地网页与 JSON API
capcut_local.py        入口（兼容 v2 的启动脚本和每日任务）
capcut_local_data/
  categories/<类别>/   config / candidates / decisions / examples / labels / taste_model …
  cache/ features/ media/   网络缓存、视频特征、示例视频（不进 Git）
docs/                  方法、调研、客户上传指南、舞蹈审美标准
已归类作者.txt / .csv   飞书已归类作者，扫描时排除（所有类别通用）
```
