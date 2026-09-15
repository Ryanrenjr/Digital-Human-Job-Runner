# Changelog — 0.1.2
## Digital Human Job Runner

**Version:** 0.1.2  
**Name:** CleanVideo Local Console V1.2  
**Release date:** 2026-06-10  
**Base version:** 0.1.1

---

## 版本定位

CleanVideo Local Console user-experience upgrade.

本版本将系统从"开发者任务运行器"升级为"可独立使用的本地制作控制台"：用户可以在浏览器内完成预览、下载、管理的完整工作流，无需手动操作文件系统。同时新增中英文界面切换，支持中英文双语操作。

---

## 新增内容

### 后端

| 新增端点 | 说明 |
|----------|------|
| `GET /jobs/{job_id}/download` | 返回 clean_video.mp4，FileResponse，支持 HTTP range 请求（视频可 seek） |
| `DELETE /jobs/{job_id}` | 删除整个 job 目录（input / output / logs）；running 且进程真实存在时返回 409 |

**新增字段 `artifacts`（注入到 GET /jobs 和 GET /jobs/{id}）：**
```json
"artifacts": {
  "clean_video_exists": true,
  "download_url": "/jobs/JOB_ID/download",
  "preview_url":  "/jobs/JOB_ID/download"
}
```

### 前端

| 新增文件 | 说明 |
|----------|------|
| `src/translations.js` | 中英文翻译字典，覆盖所有 UI 文案 |

| 组件 | 改动 |
|------|------|
| `Header.jsx` | 新增语言切换按钮（EN / 中）；支持 `t` props |
| `CreateJobForm.jsx` | 全面 i18n，表单 label / placeholder / button 均可翻译 |
| `HowToUse.jsx` | 标题、副标题、步骤全部 i18n |
| `JobQueue.jsx` | 队列标题、按钮文案、空状态 i18n |
| `JobDetail.jsx` | 详情面板所有文案 i18n；视频预览区内嵌 `<video>`；Download 按钮；Copy Windows Path；Delete 危险区 |
| `App.jsx` | 维护 `language` 状态 + `localStorage` 持久化；Handler 消息 i18n |
| `index.css` | 新增 `.lang-toggle`、`.lang-btn` 样式；新增 `.video-preview`、`.danger-zone`、`.copy-path-*`、`.detail-empty`、`.how-to-use-card`、`.step-*`、`.btn-danger` |

---

## 语言切换机制

- 状态：`useState(() => localStorage.getItem('leovisa_language') || 'en')`
- 切换时写入：`localStorage.setItem('leovisa_language', lang)`
- 刷新页面后保持上次选择
- 不自动检测浏览器语言，默认英文

---

## 未改变内容

- VoxCPM2 生成方式（`generate_voice_and_timeline_voxcpm2.py`）
- LatentSync 主脚本（`run_02_latentsync_overlap.sh`）
- CleanVideo 输出逻辑（`collect_output.py`）
- Cancel / Reset 逻辑（V1.1 保留）
- Live Progress / Window X/Y 逻辑（V1.1 保留）
- job.json 磁盘结构（向后兼容）
- 无新增数据库
- 无 Remotion 接入
- 无 WhisperX 前端流程
- 无 WebSocket（仍为 5s 轮询）

---

## 已知风险

- **删除不可撤销** — 删除任务会永久清理 input/output/logs，需要用户二次确认
- **Download 依赖文件存在** — `GET /jobs/{id}/download` 若 clean_video.mp4 不存在返回 404
- **视频预览依赖浏览器** — 需要浏览器支持 video/mp4（主流浏览器均支持）
- **串行限制不变** — 同一时间仍只允许一个任务运行
- **搜索/筛选缺失** — 任务历史较多时无搜索功能

---

## 升级方式

直接替换前后端文件，重启即可。V1 / V1.1 历史任务数据无需迁移。

```bash
# 后端（--reload 自动热重载）
conda activate base
cd ~/AI-Workspace/app/backend
uvicorn main:app --host 127.0.0.1 --port 8008 --reload

# 前端（重新安装依赖无需要，直接启动）
cd ~/AI-Workspace/app/frontend
npm run dev
```
