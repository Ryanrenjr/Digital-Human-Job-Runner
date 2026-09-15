# V1.3 VoxCPM2 声音引擎

## 已接入的能力

- 每个任务保存独立的声音快照，不依赖训练目录之后是否被删除。
- `controllable_clone` 使用 LoRA 声音模型加参考音频。
- `ultimate_clone` 首段使用 `prompt_wav_path + prompt_text`，后续段落只使用 `reference_wav_path`，避免每句话都重置韵律。
- `basic_tts` 不会误加载自定义声音的 LoRA 或参考音频；`voice_design` 只使用模型自带能力。
- 任务可选择风格、语速、质量预设；这些选择会保存到任务和 `voice_generation.json`。
- 文案按标点和语义切段，保留展示文本、口播正文与实际送入模型的文本，取消固定时长裁剪和 `atempo` 强行变速。
- 分段清理只移除开头的模型静音，不使用会在自然停顿处截断正文的 stop-silence 规则。
- `voice_design` 和 `controllable_clone` 会按 VoxCPM2 协议把自然语言 Style/Pace 放入圆括号前缀；字幕只使用正文。
- `ultimate_clone` 保持 Hi-Fi 路径：首段使用 `prompt_wav_path + prompt_text + reference_wav_path`，不注入 Style/Pace，因为官方说明 Hi-Fi 模式会忽略控制指令。
- 高质量预设使用 `cfg_value=2.0`、`inference_timesteps=25`；最高质量使用 30 步并可进行候选比较。
- VoxCPM2 的文本归一化、参考音频清理、bad-case 重试和重试阈值都显式记录。
- 每个分段记录 seed、候选数量、选中候选、预计时长、实际时长和质量分数。
- 训练语言跟随声音人物配置；可放入 `training/transcripts_reviewed.tsv` 覆盖 Whisper 草稿。
- 训练完成后保存 `references` 数组，为以后按风格选择参考音频留下接口。

## 当前引擎边界

已安装的 VoxCPM2 `generate()` 签名支持：

```text
text, prompt_wav_path, prompt_text, reference_wav_path,
cfg_value, inference_timesteps, normalize, denoise,
retry_badcase, retry_badcase_max_times,
retry_badcase_ratio_threshold
```

它没有独立的 style、pace 或 seed 参数。Style/Pace 通过官方支持的 `text="(control instruction)正文"` 协议传入，但只对 `voice_design` 和 `controllable_clone` 生效；`ultimate_clone` 不传控制前缀。`captions.json` 永远只保存正文，`voice_generation.json` 的每个 segment 才记录 `generationText` 和 `controlInstruction`。seed 通过 Torch/NumPy 的生成前状态设置实现可复现兜底，并记录在元数据中。

生成后的 ASR 控制词检查默认关闭，以免每个任务额外加载 Whisper。音频质量回归或试听对比时可设置 `DHJR_GENERATION_ASR_CHECK=1`，如果 ASR 识别出“自然、专业、严肃”等控制词，日志会输出警告，并记录在 `voice_generation.json`，不会把任务误判为失败。

## 推荐手工对比

使用同一人物视频、同一段约 20 秒文案和同一个 Ryan 声音，分别测试：

1. 声音模式：`controllable_clone`，质量：`high`，风格：`professional_natural`，语速：`natural`。
2. 声音模式：`ultimate_clone`，质量：`maximum`，语速：`natural`。
3. 保持 `controllable_clone`、同一参考音频、同一 CFG 和步数不变，只切换 `professional_natural / serious_authoritative / warm_storytelling`，再比较 `natural / slightly_fast`。

每个成品任务的 `output/voice_generation.json` 可以用来确认真实生效的模式、参考音频、CFG、推理步数和分段时长，不要只看前端百分比。
