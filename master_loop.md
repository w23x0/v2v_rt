# 24 小时调度骨架

`master_loop.py` 是一个可恢复的进程调度器，不依赖 Claude 会话持续在线。它负责保存队列状态、按阶段执行命令、失败重试和日志；Claude 可以在每轮之间修改队列或作为可选规划器提出下一批搜索词。

## 使用

```bash
cp pipeline_config.example.json pipeline_config.json
python3 master_loop.py --config pipeline_config.json --once --dry-run
python3 master_loop.py --config pipeline_config.json
```

默认每 1800 秒处理一个 job。状态写入 `pipeline_state.json`，日志写入 `pipeline.log`。这些运行时文件不应提交到 Git。

服务器上建议使用 `v2v-master-loop.service.example` 生成 systemd unit：替换 `__V2V_USER__` 和 `__V2V_REPO__`，复制到 `/etc/systemd/system/` 后执行 `systemctl enable --now v2v-master-loop`。这样 SSH 断开、Claude 会话退出或进程异常时，循环仍会由 systemd 拉起。

## 一个 job 的阶段

1. `discover`：flat 探测搜索结果。
2. `classify`：按 [数据范围与分类标准.md](数据范围与分类标准.md) 生成 `accept/review/reject` 结果。
3. `download`：只有 job 带有 `"approved": true` 才会执行；否则状态变为 `awaiting_review`。
4. `clean`：调用已有 ffmpeg 清洗脚本。
5. `asr`：调用转写脚本并写回段级结果。示例配置使用服务器现有的 `transcribe_en_mp.py`，它是首批 Valorant 英文数据专用脚本；中文和 CS 接入前需要分别把脚本的输入/输出目录参数化。

命令以 JSON 数组配置，支持 `{job_id}`、`{query}`、`{game}`、`{platform}`、`{limit}`、`{data_root}`、`{discovery_file}` 和 `{classification_file}` 占位符。`data_root` 应指向服务器数据盘（示例为 `~/v2v-data`），状态和日志仍单独放在项目目录。空命令表示该阶段跳过，方便先把队列和状态跑通。

发现结果人工检查通过后，可以用 `--approve JOB_ID` 解锁该 job，例如：

```bash
python3 master_loop.py --config pipeline_config.json --once --approve valorant-youtube-comms-001
```

探测批次内的 ID 去重由 `classify_discovery.py` 调用 `dedupe.py` 完成；跨轮次去重仍依赖采集命令中的 `--download-archive`。下载完成后再补 SHA-256 文件指纹，不能用标题相似度直接删文件。

## 与 Claude 的边界

Claude 不应该承担进程保活、断点记录或无限循环。它适合读取 `pipeline_state.json`、分类统计和失败日志，然后提出或写入下一批候选 job。真正的 24 小时运行应由 systemd、supervisord、tmux 或云平台任务托管；机器重启后重新执行同一命令即可从状态文件恢复。

在启用大批量采集前，必须先人工复核 `discover` 输出，并把 `accept/review/reject` 结果写入 job 或独立元数据文件；调度器不会仅凭标题声称“肯定有队内语音”。
