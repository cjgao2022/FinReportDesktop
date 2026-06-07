# 财报下载器

A 股上市公司财务报告批量下载桌面工具。支持新浪财经和巨潮资讯双数据源，打包为单个 `.exe` 文件，无需安装 Python 即可使用。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| 双数据源 | 同时查询新浪财经和巨潮资讯，结果自动合并去重 |
| 股票查询 | 支持 6 位股票代码（`000001`）或公司名称（`招商银行`） |
| 报告类型 | 年报 / 一季报 / 中报（半年报）/ 三季报 / 全部 |
| 年份过滤 | 可按年份缩小结果范围，支持 2000 年至今 |
| 单条下载 | 点击列表中任意一行的「下载」即可单独保存 |
| 批量下载 | 勾选多条后点击「下载选中」，后台顺序下载，界面不卡顿 |
| 自定义目录 | 下载目录可自由设置，默认为系统 `Downloads` 文件夹 |
| 实时状态 | 每行独立显示下载进度（排队中 / 下载中 / ✓ 完成 / ✗ 失败） |

---

## 使用方法（最终用户）

### 第一步：打开程序

双击 `dist\财报下载器.exe`，无需安装，直接运行。

### 第二步：填写查询条件

```
股票代码/名称  →  输入 6 位代码（如 000001）或公司名（如 平安银行）
报告类型       →  选择 年报 / 一季报 / 中报 / 三季报 / 全部
年份           →  可选，留空则查询全部年份
数据源         →  双源（默认）/ 新浪财经 / 巨潮资讯
```

按 **Enter** 或点击「查　询」。

### 第三步：下载报告

- **单条下载**：点击表格最右侧「下载」
- **批量下载**：勾选行左侧复选框（或点「全选」），再点「下载选中」

文件保存到「保存目录」输入框所指定的路径，文件名为报告标题，格式为 `.pdf`。

---

## 开发者指南

### 环境要求

- Python 3.8+
- 依赖：`requests`、`tkinter`（标准库）、`pyinstaller`（仅打包时需要）

### 安装依赖

```bash
pip install requests pyinstaller
```

### 直接运行（开发模式）

```bash
python main.py
```

### 打包为 exe

**方式一：双击脚本**

```
build.bat
```

**方式二：手动执行**

```bash
pyinstaller --onefile --noconsole --name 财报下载器 --clean main.py
```

打包产物位于 `dist\财报下载器.exe`，约 18 MB，可单独分发，目标机器无需安装 Python。

---

## 项目结构

```
FinReportDesktop/
├── main.py          # 完整源码：爬虫 + 下载 + GUI（单文件）
├── requirements.txt # 运行依赖
├── build.bat        # 一键打包脚本（Windows）
├── test_run.py      # 数据源连通性验证脚本
└── dist/
    └── 财报下载器.exe  # 打包产物（不纳入版本管理）
```

---

## 技术实现

### 架构概览

```
main.py
├── 新浪财经爬虫（sina_*）
│   ├── sina_resolve_stock()      # 股票代码/名称解析
│   ├── sina_fetch_reports()      # 公告列表抓取
│   └── sina_get_pdf_url()        # 公告详情页解析 PDF 链接
├── 巨潮资讯爬虫（cninfo_*）
│   ├── cninfo_resolve_stock()    # 股票信息解析 + orgId 推导
│   └── cninfo_fetch_reports()    # 公告列表查询（JSON API）
├── 下载工具
│   ├── sanitize_filename()       # 文件名清洗
│   └── download_pdf()            # 流式 HTTP 下载
└── GUI（MainWindow）
    ├── _build_ui()               # 界面搭建
    ├── _do_search()              # 查询（后台线程）
    ├── _start_downloads()        # 下载（后台线程）
    └── _poll()                   # 队列轮询，将线程结果回写到 UI
```

### 新浪财经数据源

| 步骤 | 接口 | 说明 |
|------|------|------|
| 1. 解析股票 | `suggest3.sinajs.cn/suggest` | GET，GBK 编码，返回 JS 变量赋值 |
| 2. 获取公告列表 | `money.finance.sina.com.cn/corp/go.php/vCB_Bulletin/...` | HTML 解析，`<div class="datelist">` |
| 3. 解析 PDF 链接 | `vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php` | 公告详情页，查找含"下载"或"PDF"的 `<a>` 标签 |

报告类型路径对应关系：

| 报告类型 | URL 路径段 |
|----------|------------|
| 年报 | `vCB_Bulletin` / `ndbg` |
| 一季报 | `vCB_BulletinYi` / `yjdbg` |
| 中报 | `vCB_BulletinZhong` / `zqbg` |
| 三季报 | `vCB_BulletinSan` / `sjdbg` |

### 巨潮资讯数据源

| 步骤 | 接口 | 说明 |
|------|------|------|
| 1. 发现 orgId | `POST hisAnnouncement/query`（searchkey 模式） | 关键词搜索取 secCode 精确匹配结果；失败时回退推导 |
| 2. 获取公告列表 | `POST cninfo.com.cn/new/hisAnnouncement/query` | JSON API，分页（每页最多 30 条） |
| 3. 下载 PDF | `static.cninfo.com.cn/{adjunctUrl}` | 响应中直接携带下载链接 |

**orgId 说明**：

巨潮资讯的 `topSearch` API 当前持续返回空列表，无法使用。各板块股票的 orgId 格式不同，无法统一推导：

| 板块 | 代码范围 | orgId 格式示例 |
|------|----------|----------------|
| 深市主板 | 000xxx / 001xxx | `gssz0{code}`（可推导） |
| 上市主板 | 600xxx / 601xxx / 603xxx | `gssh0{code}`（可推导） |
| 创业板 | 300xxx / 301xxx | `9900XXXXXXXX`（**不可推导**，需查询发现） |
| 科创板 | 688xxx | `9900XXXXXXXX`（**不可推导**，需查询发现） |
| 北交所 | 4xxxxx / 8xxxxx | `gsbj0{code}`（可推导） |

实现策略：先用 `searchkey=股票代码` 查一次公告，过滤 `secCode` 精确匹配且 orgId 前缀为 `gssz/gssh/gsbj/9900` 的条目；若无命中（如 000001 被基金代码干扰），回退到按首位数字推导的公式。

**年份过滤说明**：`seDate` 参数过滤的是公告**发布日期**，而 2025 年报通常在 2026 年 3-4 月发布。因此年份过滤改为客户端从公告标题中提取报告年度再筛选，与新浪财经保持一致。

公告类型与 `category` 字段对应关系：

| 报告类型 | category 参数值 |
|----------|----------------|
| 年报 | `category_ndbg_szsh` |
| 一季报 | `category_yjdbg_szsh` |
| 中报 | `category_bndbg_szsh` |
| 三季报 | `category_sjdbg_szsh` |
| 全部 | `""`（空字符串） |

### GUI 线程模型

UI 主线程与网络/下载线程之间通过 `queue.Queue` 通信，避免直接跨线程修改 tkinter 控件。

```
主线程                          后台线程
  │                                │
  ├─ _do_search()                  │
  │   └─ threading.Thread ────────►│ sina_fetch_reports()
  │                                │ cninfo_fetch_reports()
  │◄── queue.put("search_done") ───┤
  │                                │
  ├─ _start_downloads()            │
  │   └─ threading.Thread ────────►│ sina_get_pdf_url()
  │                                │ download_pdf()
  │◄── queue.put("row_action") ────┤
  │◄── queue.put("dl_done") ───────┤
  │                                │
  └─ _poll()  [每 80 ms 轮询队列]
```

---

## 已知限制

| 限制 | 原因 | 影响 |
|------|------|------|
| 新浪财经无法搜索 000001 | Suggest API 将该代码映射到上证指数 | 用代码 `000001` 查询时需选"巨潮资讯"来源，或改用名称"平安银行" |
| 新浪财经部分报告无 PDF | 公告详情页未提供下载链接 | 下载失败，状态标红"✗ 失败" |
| 巨潮资讯分页上限 600 条 | 代码限制最多取 20 页 × 30 条/页 | 极少数披露量极大的公司可能截断 |
| 依赖网站 HTML 结构 | 使用页面解析而非官方 API | 网站改版后需更新解析逻辑 |
| 无断点续传 | 下载中途关闭程序会产生不完整文件 | 需重新下载对应文件 |

---

## 常见问题

**Q：查询时提示"未找到匹配的股票"**
A：确认股票代码为 A 股 6 位数字，或公司名称拼写正确。部分 B 股、基金代码不在支持范围内。

**Q：下载失败（✗ 失败）**
A：可能原因：①该公告在新浪端无 PDF 下载链接（改用巨潮资讯来源重新查询）；②网络超时（稍后重试）。

**Q：文件名含乱码**
A：Windows 系统若将默认编码设为非 UTF-8，文件名可能显示异常。可在设置中将系统区域改为 UTF-8，或在命令提示符运行前执行 `chcp 65001`。

**Q：想重新打包 / 修改源码**
A：安装 Python 3.8+ 和 pip，修改 `main.py` 后双击 `build.bat` 即可重新生成 exe。
