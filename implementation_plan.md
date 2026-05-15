# VidDup — 视频重复检测器 项目计划

## 项目概述

VidDup 是一个开源的视频重复检测命令行工具，能够扫描指定目录，通过多层指纹技术识别完全相同或高度相似的视频文件。目标是做成一个可以在 GitHub 上发布的高质量开源项目。

---

## 目标与非目标

### ✅ 目标
- 检测目录中的重复/近似重复视频文件
- 支持常见视频格式（mp4, mkv, avi, mov, flv, webm 等）
- 抵抗转码、分辨率变换、轻度压缩等带来的差异
- 指纹结果缓存到本地 SQLite，支持增量扫描（新增视频不重复计算）
- 生成可读的报告（终端输出 + JSON 文件）
- 支持跨多目录扫描（`viddup scan ~/A ~/B`）
- Mac (Apple Silicon / Intel) 友好，无需 GPU
- 代码结构清晰，预留扩展钩子，易于贡献和扩展

### ❌ 非目标（当前版本）
- 不做视频内容语义理解（不用深度学习模型）
- 不做自动删除（只报告，删除由用户决定）
- 不做 Web UI（v1.0 以后考虑）
- 不做云端同步

---

## 技术栈

| 类别 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | 现代特性，类型注解 |
| CLI 框架 | `click` | 成熟的命令行框架 |
| 终端 UI | `rich` | 漂亮的进度条、表格、颜色 |
| 视频处理 | `subprocess` + 系统 ffmpeg | 直接调用 ffprobe/ffmpeg，无需 ffmpeg-python |
| 感知哈希 | `imagehash` | pHash / dHash 实现 |
| 图像处理 | `Pillow` | 帧图像处理 |
| 文件哈希 | `xxhash` | xxHash3-128，比 MD5 快 3-5x，无碰撞风险 |
| 数据库 | `sqlite3` (内置) | 指纹缓存，WAL 模式支持并发读 |
| 并行处理 | `ProcessPoolExecutor` (内置) | 多进程并行，从 v0.1 开始，规避 GIL |
| 包管理 | `uv` 或 `pip` + `pyproject.toml` | 现代 Python 项目标准 |
| 测试 | `pytest` | 单元测试 |

> **为什么不用 `ffmpeg-python`**：该库最后一次维护在 2021 年，API 反直觉。直接 `subprocess.run(["ffprobe", ...])` 更简单、更可控、少一个不稳定依赖。

> **为什么用 `xxhash` 而非 `MD5`**：xxHash3-128 速度是 MD5 的 3-5x，且无已知碰撞漏洞，更适合专业工具。

> **为什么从 v0.1 用 `ProcessPoolExecutor`**：指纹生成是 CPU 密集型任务（ffmpeg 解码 + pHash），Python GIL 导致线程池在此场景下无效，进程池可真正利用多核。

---

## 系统依赖

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
apt install ffmpeg

# 验证
ffmpeg -version
ffprobe -version
```

---

## 核心算法：三层指纹

### L1 — 文件哈希（精确副本）
- 对整个文件计算 **xxHash3-128**
- 相同哈希 = 完全相同的文件，无需进入后续层
- 速度：极快（受磁盘 I/O 限制）

### L2 — 元数据预筛（候选分组）
- 使用 `ffprobe` 提取：视频时长、分辨率、编码格式
- 只有时长差异在 **±`duration_tol`（默认 5%）** 以内的视频才进入 L3 比较
- 阈值可通过 `--duration-tol` 配置，覆盖裁片头/片尾场景
- 目的：把 O(n²) 的全量比较变成小组内比较

> ⚠️ **已知限制**：若同一视频被裁剪了大于 `duration_tol` 的片头/片尾，可能会被 L2 过滤掉（漏报）。可通过调大 `--duration-tol` 缓解。

### L3 — 多帧感知哈希（主力判定）
- 均匀抽取视频的 **10 帧**（位于 5%, 15%, 25%...95% 时间点）
- **低方差帧过滤**：检测每帧像素方差，若低于阈值（接近纯黑/纯白帧），跳过该帧并用备选时间点替代，避免误报
- 对每帧计算 **pHash**（64-bit 感知哈希）
- 比较时计算两序列的**中位数 Hamming 距离**（比平均值更鲁棒，抵抗异常帧影响）
- 距离 < 阈值（默认相似度 ≥ 0.85）→ 判定为重复

```
相似度分 = 1 - (median_hamming_distance / 64)
默认阈值: similarity >= 0.85 → 重复
```

---

## 数据库 Schema

```sql
CREATE TABLE fingerprints (
    path          TEXT PRIMARY KEY,
    file_size     INTEGER NOT NULL,
    file_mtime    REAL NOT NULL,
    file_hash     TEXT,              -- L1: xxHash3-128
    duration      REAL,             -- L2: 秒
    width         INTEGER,          -- L2: 宽
    height        INTEGER,          -- L2: 高
    codec         TEXT,             -- L2: 编码格式
    frame_hashes  TEXT,             -- L3: JSON数组，10个pHash十六进制字符串
    indexed_at    TEXT NOT NULL      -- ISO8601 时间戳
);

CREATE INDEX idx_file_hash ON fingerprints(file_hash);
CREATE INDEX idx_duration  ON fingerprints(duration);
```

> **缓存失效策略**：若文件的 `mtime` 或 `file_size` 发生变化，视为文件已更新，重新计算指纹。

> **孤儿记录清理**：`viddup status` 会检测并报告数据库中路径已不存在的记录（孤儿记录）；`viddup clear --orphans` 可单独清理孤儿记录而不清空整个数据库。

---

## 项目目录结构

```
viddup/
├── README.md
├── pyproject.toml
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI（多平台）
├── viddup/
│   ├── __init__.py
│   ├── cli.py                  # CLI 入口 (click)
│   ├── config.py               # 全局配置与常量（dataclass）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── scanner.py          # 目录扫描，支持多路径
│   │   ├── fingerprinter.py    # 三层指纹生成（ProcessPoolExecutor）
│   │   ├── database.py         # SQLite 读写封装（WAL模式）
│   │   ├── comparator.py       # 相似度比较，Union-Find 分组
│   │   └── reporter.py         # 结果格式化（Rich + JSON）
│   └── utils/
│       ├── __init__.py
│       └── ffmpeg_utils.py     # ffprobe/ffmpeg subprocess 封装
└── tests/
    ├── conftest.py
    ├── test_fingerprinter.py
    ├── test_comparator.py
    └── test_scanner.py
```

---

## CLI 接口设计

### 主命令
```bash
viddup [OPTIONS] COMMAND [ARGS]...
```

### 子命令

#### `scan` — 扫描目录并生成报告
```bash
viddup scan <目录路径> [<目录路径2> ...] [选项]

选项:
  --threshold FLOAT      相似度阈值，0.0-1.0，默认 0.85
  --frames INTEGER       每个视频抽取的帧数，默认 10
  --duration-tol FLOAT   时长容差比例，默认 0.05（±5%）
  --output PATH          报告输出路径（JSON），默认当前目录
  --db PATH              指纹数据库路径，默认 ~/.viddup/fingerprints.db
  --workers INTEGER      并行工作进程数，默认 CPU核心数
  --no-cache             忽略缓存，强制重新计算所有指纹
  --recursive/--no-recursive  是否递归扫描子目录，默认递归
  --dry-run              只显示将被处理的文件，不写入数据库
```

示例：
```bash
# 单目录扫描
viddup scan ~/Downloads/Videos --threshold 0.9

# 跨目录扫描（查找A、B两个目录间的重复）
viddup scan ~/Media/A ~/Media/B --output report.json

# 宽松时长匹配（找裁过片头的视频）
viddup scan ~/Videos --duration-tol 0.15
```

#### `status` — 查看数据库缓存状态
```bash
viddup status [--db PATH]
```
输出：已缓存视频数量、孤儿记录数、数据库大小、最近扫描时间。

#### `clear` — 清除指纹缓存
```bash
viddup clear [--db PATH] [--orphans-only] [--confirm]
```
- `--orphans-only`：只清理路径已不存在的孤儿记录

---

## 输出格式

### 终端输出示例
```
🔍 VidDup — 视频重复检测器

📂 扫描目录: /Users/you/Downloads/Videos
📹 发现视频: 347 个

⚡ L1 精确重复检测...
   发现 23 组精确重复（共 31 个文件）

🔬 L3 感知哈希指纹生成...  [████████████████] 324/324 [05:23]
   ✓ 使用缓存: 156 个
   ✓ 新增指纹: 168 个

🎯 相似度比较... 发现 12 组近似重复

─────────────────────────────────────────────
重复组 #1  相似度: 96.2%
  📹 movie_1080p.mp4     2.14 GB   1920x1080  ← 建议保留（最大文件 + 最高分辨率）
  📹 movie_720p.mp4       890 MB   1280x720

重复组 #2  相似度: 91.5%
  📹 clip_h264.mp4        450 MB   1920x1080
  📹 clip_hevc.mkv        280 MB   1920x1080  ← 建议保留（更高压缩效率）
─────────────────────────────────────────────

📊 汇总：
   精确重复组: 23 组，可释放空间: 45.2 GB
   近似重复组: 12 组，可释放空间: 18.7 GB

📄 详细报告已保存: viddup_report_20260514.json
```

### "建议保留"规则（明确定义）
优先级从高到低：
1. **最高分辨率**（width × height 最大）
2. **最大文件体积**（同分辨率时，更大 = 更少压缩损耗）
3. **路径字典序**（兜底，保证结果确定性）

### JSON 报告格式
```json
{
  "scan_time": "2026-05-14T22:00:00Z",
  "scan_paths": ["/Users/you/Downloads/Videos"],
  "total_videos": 347,
  "exact_duplicate_groups": [],
  "similar_duplicate_groups": [
    {
      "group_id": 1,
      "similarity": 0.962,
      "suggested_keep": "/path/to/movie_1080p.mp4",
      "files": [
        {
          "path": "/path/to/movie_1080p.mp4",
          "size": 2298478592,
          "duration": 7234.5,
          "resolution": "1920x1080",
          "codec": "h264"
        }
      ]
    }
  ]
}
```

---

## 扩展性设计（为未来维护预留）

- **Config dataclass**：所有运行时参数通过 `Config` 对象传递，而非散落的全局变量，方便后续加入配置文件（TOML）支持
- **Reporter 抽象**：`reporter.py` 输出格式可替换（当前 Rich + JSON，未来可加 HTML、CSV）
- **指纹层可插拔**：`fingerprinter.py` 预留 `extra_validators` 钩子，v0.3 音频指纹可作为独立验证层接入
- **`.viddup_ignore`**：v0.3 加入类 `.gitignore` 的排除规则文件

---

## 开发路线图

### v0.1 — MVP
- [x] 项目骨架（pyproject.toml, 目录结构）
- [ ] L1 文件哈希（xxHash3-128）
- [ ] ffprobe 元数据提取（subprocess）
- [ ] L3 多帧 pHash 指纹生成（含低方差帧过滤）
- [ ] ProcessPoolExecutor 多进程并行
- [ ] SQLite 缓存层（WAL 模式）
- [ ] 基础 CLI（scan 命令，支持多路径，--dry-run）
- [ ] Rich 终端输出

### v0.2 — 性能与体验
- [ ] Mac Apple Silicon ffmpeg 硬件解码加速（`-hwaccel videotoolbox`）
- [ ] 增量扫描（自动跳过已缓存且未修改的文件）
- [ ] `status` 和 `clear` 子命令（含孤儿记录清理）
- [ ] JSON 报告导出（含 suggested_keep）
- [ ] 单元测试覆盖

### v0.3 — 精度与扩展
- [ ] BK-tree 近似最近邻搜索（大规模视频库优化）
- [ ] 音频指纹辅助验证（`chromaprint` / `pyacoustid`）
- [ ] 可配置的帧采样策略
- [ ] 支持 `.viddup_ignore` 文件（类似 .gitignore）

### v1.0 — 正式发布
- [ ] 完善 README（徽章、GIF 演示、安装文档）
- [ ] GitHub Actions CI（多平台测试：macOS + Ubuntu）
- [ ] PyPI 发布

---

## pyproject.toml 参考

```toml
[project]
name = "viddup"
version = "0.1.0"
description = "A fast, local video duplicate detector"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
keywords = ["video", "duplicate", "deduplication", "cli"]

dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "imagehash>=4.3",
    "Pillow>=10.0",
    "xxhash>=3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov",
    "ruff",
    "mypy",
]

[project.scripts]
viddup = "viddup.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
```

---

## 关键技术决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 为什么不用深度学习 | 选 pHash | Mac 无独立 GPU，pHash 对转码已足够 |
| 为什么用 xxHash 而非 MD5 | xxHash3-128 | 速度 3-5x，无碰撞风险，专业工具不该用 MD5 |
| 为什么不用 ffmpeg-python | 用 subprocess | 该库 2021 年后停止维护，subprocess 更简单可控 |
| 为什么从 v0.1 用进程池 | ProcessPoolExecutor | 指纹生成是 CPU 密集型，线程池受 GIL 限制无效 |
| 为什么用中位数而非平均 Hamming | 中位数 | 对黑帧/异常帧更鲁棒，减少误报 |
| 为什么用 SQLite 而不是文件 | SQLite + WAL | 支持并发读、查询灵活、单文件便携 |
| 为什么抽 10 帧 | 10 帧 | 对 >90 分钟视频已够用，帧数可配置 |
| 为什么时长容差改为 5% | 5%（原 2%） | 给轻度裁片头/片尾场景留余地，仍可通过 --duration-tol 调整 |
| 相似度默认阈值 0.85 | 保守值 | 减少误报，用户可调高以找更多候选 |

---

*文档版本: v0.2 | 更新时间: 2026-05-14*
