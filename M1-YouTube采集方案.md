# M1 - YouTube FPS 开黑语音采集方案

> 阶段：Phase 1 / 里程碑 M1 的第一批——**小批量验证管线可行性**（不是上来就几千小时）。
> 执行位置：**UpCloud 美国服务器**（原生访问 YouTube，无需代理）。
> 建立日期：2026-08-23

---

## 一、目标

跑通「**发现 → 下载音频 + 字幕 → 存储**」整条管线，用最小批量（约 5–10 个视频）验证：
1. yt-dlp 在服务器上能正常下 YouTube（反爬、限流是否触发）
2. 能拿到**音频 + 字幕**（人工/自动）
3. 存储结构合理，能区分游戏/频道/视频类型

验证通过后，再放量到 Valorant 单游戏数千小时级（baseline 目标）。

---

## 二、采集策略（关键）

### 目标内容
**带队内语音（comms）的完整 FPS 对局长视频** —— 队友真实开黑、报点、嘲讽、文化语境，最贴近项目目标场景。

### 搜索关键词（按优先级）
| 游戏 | 搜索词模板 |
|------|-----------|
| Valorant | `valorant ranked full match comms` / `valorant comp game team voice` / `valorant immortal gameplay comms` |
| CS2 | `cs2 premiere full game comms` / `cs2 faceit level 10 comms` / `cs2 full match team voice` |

> 命门词：**`comms`** 或 **`team voice`** —— 电竞圈指"队内语音"，主播常把开黑语音录进视频。不带这俩词会搜到大量无语音的纯画面录像。

### 必须排除（用标题/时长过滤掉）
- ❌ 高光/搞笑剪辑（短、配音后制、原声被盖）：`highlights` `funny` `moments` `clip`
- ❌ 教学/解说（单人解说＝要避开的风格）：`guide` `tips` `how to` `tutorial` `explained`
- ❌ 职业比赛解说（赛事播报）：`VCT` `pro` `tournament` `champions` `major`
- ❌ 短视频：用**时长 > 20 分钟**过滤（完整对局通常 30–60 分钟）

---

## 三、服务器环境初始化（一次性）

```bash
# Ubuntu 26.04，先装依赖
sudo apt update
sudo apt install -y ffmpeg python3-pip jq

# 装 yt-dlp 并强制最新（反爬迭代快，必须最新）
pip install --user -U yt-dlp
yt-dlp -U

# 验证
yt-dlp --version
ffmpeg -version | head -1
```

> yt-dlp 必须保持最新：YouTube 反爬更新很快，旧版会撞到 "Sign in to confirm you're not a bot"。建议每周 `pipx upgrade yt-dlp` 一次。

---

## 三-B、服务器实际部署状态（已完成 2026-08-23，美西 US-SJO1）

> 下面是踩坑后的**真实可用配置**，已验证跑通。原始方案的命令缺了两个关键依赖（JS 运行时 + 反爬伪装），不补会失败。

**服务器**：`w23x@209.50.60.104`（Ubuntu 26.04，4核/8GB/752GB空闲，出口 San Jose US，原生访问 YouTube）

**已装组件**：
- `yt-dlp 2026.08.19`（用 `pipx` 装，PEP 668 环境下 pip 直接装会被拦）
- `deno 2.9.5`（**必须**：新版 yt-dlp 解析 YouTube 签名需要 JS 运行时，不装会 warning + 下载失败）
- `curl_cffi`（**必须**：已 `pipx inject` 进 yt-dlp venv，做浏览器指纹伪装，对抗 YouTube 反爬）
- `ffmpeg 8.0.1`、`jq 1.8.1`

**两个必须加的参数（原始方案没有）**：
- `--js-runtimes deno` —— 启用 deno 解析签名（不加 → 下载静默失败）
- 装 curl_cffi 后 impersonation 自动生效（不加 → "no impersonate target" 警告，抗反爬寿命短）

**采集脚本**：服务器上 `~/v2v-scripts/youtube_collect.sh`（已固化，用法见第六节）

**首批实测结果**：7 个视频 / 音频 3.2GB（wav 合计约 3.4GB），音频+字幕全部正常，内容是 NRG/SEN/100T 等职业战队的真实队内开黑语音（字幕验证为逐字对话转写）。

---

## 四、第一批：探测（不下载，先看有什么）

```bash
# 先 flat-playlist 抓搜索结果的结构化列表（不真正下载），看返回了哪些视频
# 注意：必须带 --js-runtimes deno
yt-dlp --js-runtimes deno --flat-playlist -j \
  "ytsearch30:valorant ranked full match comms" \
  | jq -r '. | "[\(((.duration//0)/60|floor))min] \(.channel) | \(.title)"'
```

**人工检查**输出：标题里有没有混进高光/教学/比赛？时长是不是都在 30 分钟以上？频道是不是真的开黑主播？

> 这一步是为了在花带宽下载前，先确认搜索词精准度。如果结果里掺了大量无关类型，就要调整搜索词或加标题过滤。
> **实测发现**：搜索 `valorant ranked full match comms` 结果极佳，15 条里 13 条是职业选手/战队排位全记录 VOD，仅 2 条短视频噪音（被时长过滤掉）。但偶有 `No Commentary`（无解说）视频混入（10小时长视频，时长过滤不掉）——这类需在**采集后用 jq 按标题过滤**排除，不要塞进 yt-dlp 的 match-filter（shell 正则转义太脆弱）。

---

## 五、第一批：下载音频 + 字幕（实测可用命令）

```bash
# 已固化成脚本 ~/v2v-scripts/youtube_collect.sh，直接用：
~/v2v-scripts/youtube_collect.sh "valorant ranked full match comms" 20 valorant
# 参数：搜索词 / 取多少条 / 存到哪个游戏目录

# 等价的裸命令（脚本内部就是这个）：
yt-dlp --js-runtimes deno \
  "ytsearch20:valorant ranked full match comms" \
  -f "bestaudio/best" -x --audio-format wav --audio-quality 0 \
  --write-subs --write-auto-subs --sub-langs "en.*" --sub-format vtt --convert-subs srt \
  --match-filter "!is_live & duration > 1200" \
  --download-archive done.txt \
  --sleep-requests 1.5 --retries 10 -N 2 \
  -o "%(uploader)s/%(id)s_%(title).50s.%(ext)s"
```

**参数说明**（这些是项目级约定，后续都沿用）：
- `-x --audio-format wav`：只要音频，语音识别用 wav（无损）
- `--write-subs --write-auto-subs`：人工字幕 + 自动字幕都要（人工优先、自动兜底）
- `--match-filter "!is_live & duration > 1200"`：**排除直播 + 时长>20分钟**，精准命中开黑长视频
- `--download-archive done.txt`：断点续传/去重，重跑不重复下
- `-N 2 --sleep-requests 1.5`：低并发+限速，避免触发风控
- `-o "%(uploader)s/..."`：按频道分目录

---

## 六、存储结构（建议）

```
~/v2v-data/
└── valorant/                          # 按游戏分
    ├── done.txt                       # 下载记录（去重用）
    └── {频道名}/
        ├── {videoId}_{标题}.wav       # 音频
        ├── {videoId}_{标题}.en.srt    # 人工字幕（若有）
        └── {videoId}_{标题}.en-auto.srt  # 自动字幕
```

后续 M2 清洗时，人工字幕和自动字幕分别处理（人工质量高用于精标，自动兜底覆盖广）。

---

## 七、验证清单（跑完检查这些）

- [ ] 下了几个文件？音频能不能正常播放（抽查前 30 秒，确认没有广告/静音段）
- [ ] **有没有字幕**？人工字幕命中率多少？自动字幕质量如何？
- [ ] 内容是不是真的开黑语音（能听到队友对话），还是只有主播单人？
- [ ] 有没有触发反爬（报错、限流、"not a bot"）？
- [ ] 总共花了多少磁盘/时间？（估算放量到 1000 小时的成本）

把这些结果反馈回来，决定是否放量、以及是否调整搜索词/过滤条件。

---

## 八、下一步（验证通过后）

1. 放量：用 `ytsearch500:` 或多个搜索词组合，攒 Valorant 单游戏首批数据
2. 并行准备中文侧调研（抖音/B站点播，需过代理）
3. 进 M2（字幕提取清洗 + 降噪）
