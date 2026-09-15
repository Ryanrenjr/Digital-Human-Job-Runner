# Changelog — 0.1.1
## Digital Human Job Runner

**Version:** 0.1.1  
**Name:** CleanVideo Local Runner V1.1  
**Release date:** 2026-06-10  
**Base version:** 0.1.0

---

## 版本定位

CleanVideo Local Runner maintenance upgrade.

解决 V1 主要运维痛点：stale running job 无法从前端恢复；LatentSync 进度不可见。
无破坏性变更，不影响现有任务数据和视频生成流程。

---

## 新增内容

### 后端

| 新增文件 / 端点 | 说明 |
|----------------|------|
| `progress_utils.py` | 动态 progress 计算模块，基于文件系统状态推断当前阶段 |
| `POST /jobs/{job_id}/cancel` | 取消 pending / failed / stale running 任务 |
| `POST /jobs/{job_id}/reset` | 重置 failed / cancelled / stale running 任务为 pending |
| `GET /jobs` | 新增动态 progress 注入（running 任务只读计算，不写磁盘） |
| `GET /jobs/{job_id}` | 同上 |

**Cancel / Reset 逻辑：**
- `finished` 任务 → 400，拒绝操作
- 检测到真实运行进程 → 409，要求人工确认
- Stale running / failed / cancelled → 200，执行操作

**Progress 计算阶段：**

```
voice_for_latentsync.wav 不存在  → voice_generation (5%)
wav 存在，clean_video 不存在     → latentsync (10%~95%，core_*.mp4 计数)
clean_video 存在，未 finished    → collecting_output (95%)
status = finished               → finished (100%)
```

**ffprobe 路径探测顺序：**
1. 系统 PATH 中的 `ffprobe`
2. `~/miniconda3/envs/latentsync/bin/ffprobe`
3. 两者均失败 → `total_windows=0`，Window 行不显示，进度条仍可用

### 前端

| 文件 | 改动 |
|------|------|
| `api.js` | 新增 `cancelJob(jobId)`、`resetJob(jobId)` |
| `App.jsx` | 新增 `handleCancelJob`、`handleResetJob` 处理函数 |
| `JobDetail.jsx` | 头部新增 **✕ Cancel** 和 **↺ Reset** 按钮；ProgressBox 新增 Window X / Y 行 |
| `index.css` | 新增 `.progress-box-windows` 样式（蓝色，tabular-nums） |

**按钮显示规则：**
- Cancel：status ≠ finished 时显示
- Reset：status 为 failed / cancelled / running 时显示
- 409 错误统一提示：*"This job may still be actively running. Please check processes before cancelling or resetting."*

---

## 未改变内容

- VoxCPM2 生成方式（`generate_voice_and_timeline_voxcpm2.py`）
- LatentSync 主脚本（`run_02_latentsync_overlap.sh`）
- CleanVideo 输出逻辑（`collect_output.py`）
- job.json 磁盘结构（向后兼容，V1 任务无需迁移）
- 无新增数据库
- 无 Remotion 接入
- 无 WhisperX 前端流程
- 无 WebSocket（仍为 5s 轮询）
- 无破坏性 API 变更（原有端点行为不变）

---

## 已知风险

- **进程检测精度** — `is_job_process_running()` 基于 `ps aux` 字符串匹配，LatentSync / VoxCPM 进程不携带 job_id，可能误判有其他任务的进程为本任务活跃
- **Window 计数回退** — 如果 LatentSync 工作目录 `overlap_full_work/` 被外部清理，`current_window` 会回到 0，但不影响实际生成
- **ffprobe 不可用** — `total_windows=0` 时 Window 行不显示，进度条会在 10% 保持到 collecting_output 阶段
- **串行限制不变** — 同一时间仍只允许一个任务运行

---

## 升级方式

直接替换后端文件，重启 uvicorn 即可。V1 历史任务数据无需迁移。

```bash
# 重启后端
conda activate base
cd ~/AI-Workspace/app/backend
uvicorn main:app --host 127.0.0.1 --port 8008 --reload

# 重启前端（如需）
cd ~/AI-Workspace/app/frontend
npm run dev
```
