# Version History
## Digital Human Job Runner

---

## 0.1.2 — CleanVideo Local Console V1.2

**Version:** 0.1.2  
**Name:** CleanVideo Local Console V1.2  
**Status:** Working  
**Date:** 2026-06-10

### 新增功能

- **Video preview** — finished 任务内嵌视频播放器（`<video controls>`），支持 seek
- **Direct download** — 浏览器直接下载 clean_video.mp4
- **Copy Windows path** — 一键复制 Windows Desktop 输出路径
- **Delete job** — 删除任务（input / output / logs 全部清理）
- **Active job protection** — running 且进程存在时禁止删除（409）
- **How to Use** — 首页新增 5 步使用流程说明模块
- **UI upgrade** — Imperial College London 风格全面升级（阴影、圆角、排版、间距）
- **Artifacts metadata** — GET /jobs 和 GET /jobs/{id} 返回 `artifacts` 字段
- **Download endpoint** — `GET /jobs/{job_id}/download`（FileResponse，支持 range 请求）
- **Delete endpoint** — `DELETE /jobs/{job_id}`
- **Chinese/English switch** — Header 语言切换按钮，localStorage 持久化，默认英文

### 暂未实现（V2+ 待考虑）

- Duplicate Job / Copy Job
- FinalVideo / Remotion 包装（字幕、BGM、片头片尾）
- WhisperX 字幕生成流程前端接入
- BGM / endcard / title wrapper
- 用户登录与权限管理
- 素材上传（背景视频、参考音频）
- 多任务队列自动串行执行
- 任务历史搜索 / 筛选

### 已知限制

- 同一时间只能运行一个任务（串行）
- 视频预览依赖浏览器对 mp4 的支持
- 删除操作不可撤销
- 进程检测基于 `ps aux` 字符串匹配，非 100% 精确

---

## 0.1.1 — CleanVideo Local Runner V1.1

**Version:** 0.1.1  
**Name:** CleanVideo Local Runner V1.1  
**Status:** Working  
**Date:** 2026-06-10

### 新增功能

- **Cancel stale job** — `POST /jobs/{job_id}/cancel`
- **Reset stale job** — `POST /jobs/{job_id}/reset`
- **Active process detection** — cancel / reset 前检测真实进程
- **Live progress calculation** — `progress_utils.py` 动态计算阶段和进度
- **LatentSync window progress** — 实时统计 `core_*.mp4` 数量
- **Frontend Window X / Y** — JobDetail ProgressBox 显示 window 进度行

---

## 0.1.0 — CleanVideo Local Runner V1

**Version:** 0.1.0  
**Name:** CleanVideo Local Runner V1  
**Status:** Working  
**Date:** 2026-06-10

### 已完成功能

- **Frontend** — React 18 + Vite 5，实时任务状态轮询
- **Backend API** — FastAPI，127.0.0.1:8008
- **JSON job storage** — 文件型任务存储，无数据库
- **Background selection** — 4 个背景（boss_01 ~ boss_04）
- **CleanVideo generation** — VoxCPM2 → LatentSync 六步流水线
- **Desktop output** — 自动拷贝至 Windows 桌面
- **Shutdown after done** — 任务完成后可选自动关机

---

<!-- New versions go above this line -->
