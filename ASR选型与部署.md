# ASR 选型与部署（CPU 推理）

> 阶段：Phase 1 / M2 下游。用户决定自跑 CPU ASR 转文字，不用 YouTube 自动字幕。
> 选型调研：2026-08-23（实时验证活跃度）。部署：**英文已全量跑通（2026-08-29）**。

---

## 〇、最终选型（中英分开，2026-08-29 定，附实测）

**中英数据分开，各用对各自语言最优的模型**（不在一个模型里混用）：

| 数据侧 | 模型 | 推理 | 实测 | 状态 |
|--------|------|------|------|------|
| **中文** | **SenseVoice-Small**（FunASR） | CPU int8 | ~25–28x | 已缓存，B站/中文开黑用 |
| **英文** | **faster-whisper distil-large-v3** | CPU int8 | **~5.8–6x** | ✅ 已装、已全量转完 7 文件 |

> 英文为什么不用 whisper-large 而是 distil-large-v3：CPU 4 核上 large 系太重（large-v3-turbo 4.3x、medium 5x），distil 是英文专用蒸馏版，7x 且游戏黑话/语境明显更好（base/small 术语感人）。

**英文-side 全量实测（2026-08-29，4 核 EPYC，cpu_threads=4）：**

| 文件（概取） | 时长(s) | 转写wall | 段数 |
|------|--------|---------|------|
| MU2FzpXgfW8（Voice Comms 90min）| 5192 | —（首进程）| 4573 |
| AR1UTGB_200K（100T vs FAZE）| 2520 | ~870s | 1678 |
| BQ（SEN Jett）| 1697 | 283s | 666 |
| QFcMs（C9 OXY）| 1892 | 308s | 859 |
| VODb4（SEN ZOMBS）| 1787 | 308s | 685 |
| g_t1my（100T Asuna）| 2554 | 399s | 1143 |
| l5Rk（NRG s0m）| 1993 | 334s | 1032 |

**合计：7 文件 / 17635s≈4.9 小时 音频 → 全部转完 wall≈26.5min（10x+）**。产物在 `~/v2v-data/transcripts/valorant/*.json`（带 start/end+text）。剩余小文件可断点续跑（脚本自动 skip 已有的）。

---

| 组件 | 选型 | 理由 |
|------|------|------|
| **ASR 主模型** | **SenseVoice-Small**（FunAudioLLM） | 中文优于 Whisper；自带音频事件检测（BGM/枪声/笑声标标签而非幻听）；非自回归 CPU ~140x 实时；q8 仅 254MB |
| **VAD** | **FSMN-VAD**（FunASR 配套） | 与 SenseVoice 时间戳对齐好；零额外依赖；CPU <1ms |
| **运行时** | **FunASR Python**（起步）→ 稳定后切 llama.cpp GGUF 二进制 | Python 功能全（事件标签+标点），GGUF 版生产环境省内存 |
| **降噪** | **不做独立降噪** | SenseVoice 事件检测已覆盖 BGM/枪声；降噪损语音+加 CPU 负担。仅实测发现误触发时加 RNNoise |

## 二、为什么不是 Whisper

唯一原因是**嘈杂游戏语音**：Whisper 系在干净音频上很强，但 BGM/枪声下**容易幻听出一长串无关中英文**（社区高频投诉）。SenseVoice 的 AED 能力让它在我们的场景里质的区别——会说"这段是 BGM"而不是乱编。

英文兜底（若 SenseVoice 英文不够好，如游戏术语）：可叠加 faster-whisper `large-v3-turbo` int8（547MB）做英文分支。

## 三、排雷（调研排除项）

- ❌ **moonshine / distil-whisper：只支持英文**，不能单独覆盖中文需求
- ❌ **DeepFilterNet：已停更**（最后更新 2024-10），不押注；要降噪用 RNNoise
- ❌ **PaddleSpeech：准停更**
- ⚠️ **SenseVoice "50+ 语言"是营销话术**：Small 实际只支持 zh/en/ja/ko/yue——对中英够用

## 四、部署方案（待服务器验证）

**路线 A — FunASR Python（起步首选，功能全）：**
```bash
pip install funasr modelscope torch torchaudio  # CPU 版 torch
```
```python
from funasr import AutoModel
model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    vad_kwargs={"max_single_segment_time": 30000},
    device="cpu", disable_update=True,
)
res = model.generate(input="audio.wav", language="auto", use_itn=True, batch_size_s=60)
# rich_transcription 含文本 + <|BGM|> <|COUGH|> <|LAUGHTER|> 等事件标签
print(res[0]["text"])
```

**路线 B — llama.cpp GGUF 二进制（生产，省内存）：**
- `sensevoice-small-q8.gguf`（254MB）+ `fsmn-vad.gguf`
- 参考 FunASR/runtime/llama.cpp

## 五、部署验证结果（2026-08-23 已跑通）

**环境**：venv `~/venvs/funasr`（Python 3.14 + torch 2.13.0+cpu + funasr 1.4.3 + modelscope）

**性能（CPU 4核，实测）**：
- 模型加载：42s（首次）/ 4.5s（已缓存）
- **转写：28x 实时**（2 分钟音频 4.3 秒处理；30 秒音频 1.4 秒）
- 全量 4.9 小时清洗音频预计 ~10 分钟转完
- 模型缓存占 901MB

**转写质量验证**（NRG 战队 Valorant 队内语音）：
- 正确识别为英语（`<|en|>`）
- 检测到无人说话段（`<|nospeech|>`）——省了无效输出
- 内容是真实战术沟通："smokes"/"tap and go through"/"hit for 80"/"kill kill" 等

**已知问题（后续优化）**：
1. 游戏术语识别一般（"roll"/"lyricing mid" 等误识别）→ 需要 FPS 热词表（M3）
2. 输出带 `<|...|>` 标签 → 用正则清洗成纯文本（已实现）
3. SenseVoice "50+语言"仅营销，Small 实际 zh/en/ja/ko/yue（够用）

**测试脚本**：`/tmp/asr_test2.py`（含标签清洗），样本在 `/tmp/asr-test/`

## 六、下一步

1. 写正式转写脚本（遍历 cleaned 目录，输出带时间戳的文字 + JSON）
2. 全量转写 4.9 小时清洗音频
3. 对标 YouTube 字幕评估准确率（WER）
4. 决定是否加英文兜底分支（faster-whisper）
5. 进 M3：用 LLM 辅助打"游戏/内容类型"标签（你人工把关），不需要做中英配对翻译（放弃完美配对，见项目计划）
