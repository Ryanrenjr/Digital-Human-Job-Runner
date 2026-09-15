# V1 / V1.1 Acceptance Checklist
## Digital Human Job Runner

**Date:** 2026-06-10  
**Version:** 0.1.1

---

## 验收方法说明

- `[ ]` 表示待测试
- `[x]` 表示已通过
- `[!]` 表示已知风险或限制，无需修复

---

## 一、后端接口验收（V1）

### 1. Health 检查

```bash
curl http://127.0.0.1:8008/health
```

**期望响应：**
```json
{"status": "ok", "service": "Digital Human Job Runner", "version": "0.1.0"}
```

- [ ] 状态码 200
- [ ] `status` 字段为 `"ok"`

---

### 2. Backgrounds API 测试

```bash
curl http://127.0.0.1:8008/backgrounds
```

**期望响应：** 返回 4 个背景对象数组

- [ ] 状态码 200
- [ ] 包含 `boss_01` ~ `boss_04` 共 4 个条目
- [ ] 每条包含 `id`、`name`、`path`、`description`

---

### 3. 创建 Job 测试

```bash
curl -X POST http://127.0.0.1:8008/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "title": "测试任务",
    "subtitle": "验收测试",
    "keywords": ["测试"],
    "script": "这是一条验收测试文案。",
    "background_id": "boss_01",
    "output_type": "clean_video",
    "shutdown_after_done": false
  }'
```

- [ ] 状态码 200
- [ ] 响应包含 `job_id`（格式 `YYYYMMDD_HHMMSS_video_job`）
- [ ] `~/AI-Workspace/jobs/JOB_ID/job.json` 文件存在
- [ ] `job.json` 中 `status` 为 `"pending"`

---

### 4. 启动 Job 测试

```bash
curl -X POST http://127.0.0.1:8008/jobs/JOB_ID/run
```

- [ ] 状态码 200
- [ ] 响应包含 `pid`（进程 ID > 0）
- [ ] `job.json` 中 `status` 变为 `"running"`（可能需要几秒）

**重复启动同一任务（期望 400）：**
```bash
curl -X POST http://127.0.0.1:8008/jobs/JOB_ID/run
```
- [ ] 状态码 400

**同时运行另一任务（期望 409）：**
```bash
curl -X POST http://127.0.0.1:8008/jobs/OTHER_JOB_ID/run
```
- [ ] 状态码 409

---

### 5. 查看 Log 测试

```bash
curl http://127.0.0.1:8008/jobs/JOB_ID/log
```

- [ ] 状态码 200
- [ ] 响应包含 `log` 字段（字符串）
- [ ] 日志包含 `Run started at` 字样

**不存在的 job_id（期望 404）：**
```bash
curl http://127.0.0.1:8008/jobs/nonexistent_job/log
```
- [ ] 状态码 404

---

## 二、前端验收（V1）

### 6. 前端创建任务测试

1. 打开 `http://127.0.0.1:5173`
2. 确认右上角状态点为绿色（后端在线）

- [ ] 页面正常加载，无 console error
- [ ] Header 状态点为绿色
- [ ] Background 下拉框包含 boss_01 ~ boss_04 选项
- [ ] 填写 Title、Script、选择背景后点击 **Create Job**
- [ ] 页面顶部出现成功横幅（绿色）
- [ ] Job Queue 中出现新任务卡片，状态为 `pending`

---

### 7. 前端运行任务测试

- [ ] 点击任务卡片上的 **▶ Run** 按钮
- [ ] 成功横幅出现：`Job started: JOB_ID`
- [ ] 任务卡片状态变为 `running`（5s 轮询后刷新）
- [ ] 点击任务卡片展开 Job Detail
- [ ] Log 区域出现日志内容（running 时 5s 自动刷新）
- [ ] 任务完成后状态变为 `finished` 或 `failed`

---

### 8. 输出文件检查

任务完成后（status = finished）：

```bash
ls -lh ~/AI-Workspace/jobs/JOB_ID/output/
```

- [ ] `clean_video.mp4` 存在，大小 > 1MB
- [ ] `voice.wav` 存在
- [ ] WSL 路径：`~/AI-Workspace/jobs/JOB_ID/output/clean_video.mp4`
- [ ] Windows 桌面：`<Windows output directory>\JOB_ID_clean_video.mp4`

---

## 三、shutdown_after_done 验收（V1）

### 9. shutdown_after_done=false 测试（已通过）

已通过自动化测试（2026-06-10）：

- [x] `finished + shutdown_after_done=false` → 跳过关机
- [x] `running + shutdown_after_done=true` → 跳过关机（未完成不关机）
- [x] 损坏的 job.json → 跳过关机（容错）

---

### 10. shutdown_after_done=true — 人工确认

> **注意：** 此测试会触发真实关机倒计时，60 秒内请执行取消命令。

步骤：
1. 创建任务时勾选 "Shutdown after done"
2. 运行任务，等待完成
3. 观察日志末尾是否出现关机提示
4. 立即执行取消命令：`shutdown /a`

- [ ] 日志末尾出现 `System will shut down in 60 seconds`
- [ ] 60 秒内执行 `shutdown /a` 成功取消
- [ ] 任务 `status` 仍为 `finished`（关机逻辑不改变任务状态）

---

## 四、Cancel / Reset 验收（V1.1）

### 11. Stale running job — cancel 测试

**前置条件：** 存在一个 status=running 但进程已不存在的 job（WSL 重启后常见）

```bash
curl -X POST http://127.0.0.1:8008/jobs/STALE_JOB_ID/cancel
```

- [ ] 状态码 200
- [ ] 响应中 `status` 为 `"cancelled"`
- [ ] `error_message` 为 `"Cancelled by user."`
- [ ] `finished_at` 有值

---

### 12. Cancelled job — reset 测试

```bash
curl -X POST http://127.0.0.1:8008/jobs/CANCELLED_JOB_ID/reset
```

- [ ] 状态码 200
- [ ] 响应中 `status` 为 `"pending"`
- [ ] `started_at`、`finished_at`、`error_message` 均为 null
- [ ] `progress.stage` 为 `"pending"`、`progress.percent` 为 0

---

### 13. Finished job reset 被拒绝测试

```bash
curl -X POST http://127.0.0.1:8008/jobs/FINISHED_JOB_ID/reset
```

- [ ] 状态码 400
- [ ] `detail` 包含 "Cannot reset a finished job"

---

### 14. Active running job — cancel/reset 被 409 拒绝测试

> **前置条件：** 有真实任务正在运行（run_cleanvideo_job.sh 进程存在）

```bash
curl -X POST http://127.0.0.1:8008/jobs/REAL_RUNNING_JOB_ID/cancel
curl -X POST http://127.0.0.1:8008/jobs/REAL_RUNNING_JOB_ID/reset
```

- [ ] 两者均返回状态码 409
- [ ] `detail` 包含 "appears to be actively running"

---

### 15. 前端 Cancel / Reset 按钮测试

- [ ] 打开一个 status=failed 或 status=cancelled 的任务 JobDetail
- [ ] 头部显示 **✕ Cancel** 和 **↺ Reset** 按钮
- [ ] 点击 **↺ Reset**，任务变为 pending，显示成功横幅
- [ ] status=finished 的任务 JobDetail 中 **不显示** Cancel / Reset 按钮

---

## 五、动态 Progress 验收（V1.1）

### 16. Voice generation 进度显示测试

任务 running 且 `voice_for_latentsync.wav` 尚未生成时：

```bash
curl -s http://127.0.0.1:8008/jobs/JOB_ID | python3 -m json.tool | grep -A6 '"progress"'
```

- [ ] `stage` 为 `"voice_generation"`
- [ ] `percent` 为 5
- [ ] `message` 为 `"Generating voice audio"`

---

### 17. LatentSync window 进度显示测试

任务 running 且 LatentSync 正在生成时：

```bash
# 观察 core_*.mp4 数量增长
ls ~/AI-Workspace/projects/LatentSync/data/overlap_full_work/core_*.mp4 | wc -l

# 同时观察 API progress
curl -s http://127.0.0.1:8008/jobs/JOB_ID | python3 -m json.tool | grep -A6 '"progress"'
```

- [ ] `stage` 为 `"latentsync"`
- [ ] `current_window` 与 `core_*.mp4` 数量一致
- [ ] `total_windows` > 0（ffprobe 可用时）
- [ ] `percent` 在 10~95 之间
- [ ] 前端 JobDetail ProgressBox 显示 `Window X / Y` 行（蓝色）

---

### 18. Finished 100% 显示测试

任务完成后：

```bash
curl -s http://127.0.0.1:8008/jobs/JOB_ID | python3 -m json.tool | grep -A6 '"progress"'
```

- [ ] `stage` 为 `"finished"`
- [ ] `percent` 为 100
- [ ] 前端 JobDetail ProgressBox 进度条为绿色，100%

---

## 六、已知风险与限制

### 已解决（V1.1）

- ~~**[!]** V1 不提供前端 Reset/Cancel 按钮，需手动操作~~ → V1.1 已提供
- ~~**[!]** LatentSync 进度不实时更新，只能通过日志查看~~ → V1.1 已实现

### 仍然存在

- **[!]** `run_cleanvideo_job.sh` 无 executable bit，但 runner.py 使用 `bash script.sh` 调用，**不影响运行**
- **[!]** 任务日志只保留最近 200 行（API 限制）；完整日志在 `~/AI-Workspace/jobs/JOB_ID/logs/run.log`
- **[!]** `DigitalHumanOutput/` 每次任务开始时清空，不保留历史输出
- **[!]** 进程检测（`ps aux` 字符串匹配）非 100% 精确；LatentSync 等进程不携带 job_id
- **[!]** ffprobe 不在 conda base 时，`total_windows=0`，Window 行不显示（进度条仍可用）
- **[!]** 如果 LatentSync 工作目录被外部清理，`current_window` 可能回到 0

---

## 七、V1.2 验收

**Version:** 0.1.2  
**Date:** 2026-06-10

---

### 19. Download 端点测试

```bash
# 任务完成后
curl -I http://127.0.0.1:8008/jobs/JOB_ID/download
```

- [ ] 状态码 200
- [ ] `Content-Type: video/mp4`
- [ ] `Accept-Ranges: bytes`（支持 range 请求 / seek）

**文件不存在时（期望 404）：**
```bash
curl -I http://127.0.0.1:8008/jobs/JOB_ID/download  # 任务未完成
```
- [ ] 状态码 404

---

### 20. Delete 端点测试

```bash
curl -X DELETE http://127.0.0.1:8008/jobs/FINISHED_JOB_ID
```

- [ ] 状态码 200
- [ ] `~/AI-Workspace/jobs/JOB_ID/` 目录已被删除

**running 且进程真实存在时（期望 409）：**
```bash
curl -X DELETE http://127.0.0.1:8008/jobs/REAL_RUNNING_JOB_ID
```
- [ ] 状态码 409
- [ ] `detail` 包含 "appears to be actively running"

---

### 21. Artifacts 字段测试

```bash
curl -s http://127.0.0.1:8008/jobs/FINISHED_JOB_ID | python3 -m json.tool | grep -A4 '"artifacts"'
```

- [ ] `clean_video_exists` 为 `true`（finished + 文件存在）
- [ ] `download_url` 为 `"/jobs/JOB_ID/download"`
- [ ] `preview_url` 为 `"/jobs/JOB_ID/download"`

**pending / running / failed 任务：**
- [ ] `clean_video_exists` 为 `false`
- [ ] `download_url` 和 `preview_url` 均为 `null`

---

### 22. 前端视频预览测试

**前置条件：** 存在一个 status=finished 且 clean_video.mp4 存在的任务

- [ ] 点击任务卡片展开 JobDetail
- [ ] JobDetail 中出现视频播放区域（`<video>` 标签）
- [ ] 视频可以在浏览器内播放（点击播放按钮）
- [ ] 视频支持 seek（拖动进度条）

---

### 23. 前端下载 MP4 测试

- [ ] finished 任务 JobDetail 中显示 **↓ Download MP4** 按钮
- [ ] 点击后浏览器触发文件下载
- [ ] 下载文件名格式为 `JOB_ID_clean_video.mp4`
- [ ] finished 任务 Job Queue 卡片上显示 **↓ MP4** 按钮，点击同样可下载

---

### 24. 前端复制 Windows 路径测试

- [ ] finished 任务 JobDetail 中显示 Windows 路径行
- [ ] 点击 **Copy Path** 按钮后，按钮文字变为 **✓ Copied**
- [ ] 2 秒后按钮文字恢复为 **Copy Path**
- [ ] 粘贴剪贴板内容确认为正确的 Windows 输出路径（`<Windows output directory>\...`）

---

### 25. 前端删除任务测试

- [ ] pending / finished / failed / cancelled 任务的 Job Queue 卡片上显示 **✕** 按钮
- [ ] running 任务的卡片上**不显示** **✕** 按钮
- [ ] 点击 **✕** 后出现确认对话框
- [ ] 确认后任务从 Job Queue 中消失
- [ ] `~/AI-Workspace/jobs/JOB_ID/` 目录被删除
- [ ] JobDetail 中的 **Delete Job** 按钮同样有效

---

### 26. How to Use 模块测试

- [ ] 首页左侧面板（创建表单下方）显示 How to Use 卡片
- [ ] 显示 5 个步骤（01 ~ 05）
- [ ] 步骤编号、标题、描述均正常渲染

---

### 27. 中英文切换测试

- [ ] Header 右上角显示 **EN** 和 **中** 两个按钮
- [ ] 默认显示英文界面（`EN` 按钮高亮）
- [ ] 点击 **中** 按钮后，所有 UI 文案切换为中文
- [ ] 再次点击 **EN** 按钮后，切换回英文
- [ ] 切换覆盖范围：表单 label、按钮文字、使用流程步骤、任务队列标题/按钮、任务详情标签

---

### 28. 语言设置持久化测试

- [ ] 切换为中文后，刷新页面（F5）
- [ ] 刷新后界面仍显示中文
- [ ] 打开浏览器 DevTools → Application → Local Storage 确认 `leovisa_language` 键值为 `"zh"`
- [ ] 切换回英文并刷新，`leovisa_language` 键值为 `"en"`

---

### 29. UI 整体验收（V1.2）

- [ ] Imperial College 风格 UI 正常显示（深蓝 Header、卡片圆角阴影）
- [ ] 无 console error（React / API 相关）
- [ ] running 任务卡片无删除按钮（保护措施）
- [ ] finished 任务的视频预览仅在 `clean_video_exists=true` 时显示

---

## 验收结论

| 模块 | 状态 |
|------|------|
| 目录结构 | ✓ V1 完成 |
| 背景素材管理 | ✓ 4个素材全部存在 |
| job.json 数据结构 | ✓ V1 完成 |
| prepare_job.py | ✓ V1 完成 |
| collect_output.py | ✓ V1 完成 |
| run_cleanvideo_job.sh | ✓ V1 完成 |
| create_test_job.py | ✓ V1 完成 |
| FastAPI 后端（9端点） | ✓ V1 完成 |
| React 前端 | ✓ V1 完成 |
| shutdown_after_done | ✓ V1 逻辑已验证 |
| Cancel / Reset API | ✓ V1.1 完成 |
| Active process detection | ✓ V1.1 完成 |
| Dynamic progress injection | ✓ V1.1 完成（6场景测试通过） |
| LatentSync window display | ✓ V1.1 完成 |
| Download endpoint | [ ] V1.2 待验收 |
| Delete endpoint | [ ] V1.2 待验收 |
| Artifacts metadata | [ ] V1.2 待验收 |
| Video preview (frontend) | [ ] V1.2 待验收 |
| Download MP4 button | [ ] V1.2 待验收 |
| Copy Windows path | [ ] V1.2 待验收 |
| Delete job (frontend) | [ ] V1.2 待验收 |
| How to Use guide | [ ] V1.2 待验收 |
| Chinese/English switch | [ ] V1.2 待验收 |
| Language persistence | [ ] V1.2 待验收 |
| UI upgrade (Imperial) | [ ] V1.2 待验收 |
