# Spark Active Companion Demo

这是一个运行在 NVIDIA DGX Spark 上的竞赛演示，不是通用产品。系统把模型推理、
确定性策略、用户动作授权和执行分开：Step3 只输出结构化状态候选与建议，不能授权或
执行；音乐与 AC 使用独立 `action_id` 并分别授权。

比赛开发征文：[《让陪伴机器人先问一句》](征文-让陪伴机器人先问一句.md)。

## 演示能力

| 能力 | 当前实现 |
| --- | --- |
| Step3-VL | 在 DGX 私有网络中输出严格 JSON；后端直接选择最高置信度状态，不再要求用户确认情绪 |
| StepAudio | 固定合成 WAV 的 ASR、已选状态的回复措辞、异步 WAV TTS；不决定状态、授权或动作 |
| 视觉 | 固定合成场景；可选私有 Demo 媒体，浏览器不能指定任意文件 |
| 天气 | 仅由 `external-connector` 访问 Open-Meteo；失败时明确显示缓存或固定 Demo 降级 |
| 音乐 | 授权后优先取 Audius 预览；不可用时交付仓库内原创 WAV；浏览器 `playing` 事件后才记为成功 |
| AC | 始终是 Mock，不控制实体设备，不宣称物理动作成功 |
| 记忆 | SQLite 只保存确认偏好、最多 50 条脱敏摘要、动作与审计，不保存原始文本或音视频 |

主链路为：

```text
固定合成输入 / 合成文本
  -> Step3 结构化候选
  -> 后端选择最高置信度状态
  -> 回复与确定性策略
  -> 用户分别授权音乐 / AC Action
  -> 浏览器临时播放 TTS 或音乐
```

“选择最高置信度状态”不等于模型拥有授权能力。`state-confirmation` 接口已禁用，
但所有有外部效果的动作仍必须获得用户对相应 `action_id` 的明确授权。

## 技术栈与边界

- 后端：Python 3.11、Pydantic 2、Uvicorn、SQLite。
- 前端：React 19、TypeScript 7、Vite 8。
- 模型：既有 Step3-VL/vLLM 与 StepAudio HTTP 服务；模型和权重不在本仓库。
- 部署：NVIDIA DGX Spark、Docker Compose、Windows SSH loopback。
- INTERNET：仅 `external-connector` 可出网，且请求必须通过 Privacy Guard。

完整清单见 [技术栈](docs/TECH_STACK.md)，许可证边界见
[第三方声明](THIRD_PARTY_NOTICES.md)。项目代码使用 [MIT License](LICENSE)。

## 从新环境部署需要什么

本仓库包含 Demo 自有组件的完整源码、Console、Track Catalog、
`external-connector`、部署/回滚脚本、测试和合成演示资产。但它不是模型发行包，
不会提交模型权重、SSH 配置或真实 API 凭据。

从新环境部署还需要：

- DGX 上已经运行并可通过私有网络访问的 Step3-VL 与 StepAudio 服务；
- Docker 网络 `companion-private`，以及 `step3-vl:8000`、`stepaudio:8010` 别名；
- 能够无 `sudo` 使用 Docker 的现有 SSH 账号；
- DGX 已缓存 `nvcr.io/nvidia/vllm:26.06-py3`，或者能够从 NVIDIA NGC 拉取它；
- 如需 Audius，再另外提供 Git 忽略的歌单配置和凭据。未配置时使用仓库内原创 WAV。

检查 NVIDIA 基础镜像是否已经存在：

```sh
docker image inspect nvcr.io/nvidia/vllm:26.06-py3
```

因此，仓库足以部署全部 Demo 自有服务，但不能单独从零创建 Step3/StepAudio 模型
基础设施。详细前置条件见 [DGX Spark 部署说明](docs/DEPLOYMENT_DGX_SPARK.md)。

## 仓库准备

在仓库根目录执行：

```powershell
python -m pip install -r requirements.txt
npm --prefix console ci
npm --prefix console run build
```

本机开发后端（模型经已有 SSH 隧道访问）可使用：

```powershell
$env:SPARK_STEPAUDIO_URL = "http://127.0.0.1:18010"
$env:SPARK_STEP3_URL = "http://127.0.0.1:18000"
python -m uvicorn backend.app.api:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/console/`。不要把真实 SSH 主机、完整 IP、私钥、
API Token、`.env`、运行时数据库或真实用户音视频写入仓库。

## DGX Spark 部署

部署脚本构建本地源码镜像并部署 Demo backend、Track Catalog 和
`external-connector`。它不会停止、重启或修改 Step3/StepAudio 容器，也不会开放
新的 DGX 主机端口。

```powershell
$SparkSshAlias = "your-existing-dgx-ssh-alias"

.\scripts\deploy_dgx_spark.ps1 `
  -SshAlias $SparkSshAlias `
  -InstallStepAudioDemoAsset

$Tunnel = .\scripts\start_dgx_console_tunnel.ps1 `
  -SshAlias $SparkSshAlias

Start-Process $Tunnel.local_url
```

固定 StepAudio 语音资产的安装是显式开关：目标文件哈希不同时脚本停止且不覆盖；
权限不足时停止，不使用 `sudo`。完整的拓扑、验收、回滚和容器不变性检查见
[DGX Spark 部署说明](docs/DEPLOYMENT_DGX_SPARK.md)。Windows 访问步骤见
[Windows 控制台说明](docs/WINDOWS_CONSOLE_ACCESS.md)。

## Audius 配置

Audius 是可选能力。LLM 不搜索或选择曲目；确定性策略只选择五个固定目录：
`RELAX`、`COMFORT`、`UPLIFT`、`COOLDOWN`、`NEUTRAL`。人工核准的歌单 URL 与
凭据必须保存在 Git 忽略的本地文件中，不能进入前端、Track Catalog 或日志。

本地目录配置：

```powershell
Copy-Item data/audius_playlists.example.json data/audius_playlists.local.json
notepad data/audius_playlists.local.json
.\scripts\start_audius_catalog.ps1
```

DGX 部署读取两个只读目录：

- `SPARK_AUDIUS_CONFIG_DIR`：包含 `audius_playlists.local.json`。
- `SPARK_AUDIUS_SECRETS_DIR`：包含 `audius_api_key` 与
  `audius_bearer_token` 两个纯文本文件。

首次启用由 DGX 管理员在 release 目录使用 Compose override，并且只设置目录路径，
不在命令行回显凭据：

```sh
export SPARK_AUDIUS_CONFIG_DIR=/absolute/private/config-directory
export SPARK_AUDIUS_SECRETS_DIR=/absolute/private/secrets-directory
docker compose -p spark-active-companion-demo \
  -f docker-compose.dgx.yml \
  -f docker-compose.dgx.audius.yml up -d external-connector
```

之后 `deploy_dgx_spark.ps1` 会从既有 `external-connector` 读取并保留这两个只读挂载；
若只存在一个挂载或目录失效，部署会停止。不要把目录变量误写为凭据值。

真实 Audius 能否播放还受公开 Track 可用性、地区/网关限制、网络延迟和浏览器自动
播放策略影响。目录或网络失败会明确显示降级原因并使用本地原创 WAV；自动化中的
`playing` 事件不代表已经通过人耳验收。

## 演示操作

1. 打开“对话”，输入合成示例文本并点击“分析并发送”。
2. Step3 返回候选后点击“继续这次对话”；后端直接采用最高置信度状态并生成回复。
3. 若产生音乐或 AC Action，分别批准或拒绝；没有批准就不会执行。
4. TTS 文字先显示，再异步生成。浏览器阻止自动播放时使用手动播放按钮。
5. 音乐授权后，查看来源 `AUDIUS_PREVIEW` 或 `LOCAL_FALLBACK` 和降级原因。
6. 在“审计”页核对网络范围、真实后端事件、外发最小载荷和不同 Action ID。
7. 刷新不会自动重新生成或播放语音；待授权动作在服务重启后不会自动执行。

AC 永远是 Mock。浏览器报告开始播放只说明媒体元素进入 `playing`，不证明扬声器
实际可听；最终提交前仍需在 Windows 上完成人工听音验收。

## API 摘要

- `POST /v1/analysis/text`：分析合成文本并返回结构化候选。
- `POST /v1/analysis/text/{analysis_id}/sessions`：一次性继续并直接选择最高状态。
- `POST /v1/live/sessions/{session_id}/speech-demo`：使用服务端固定合成语音。
- `POST /v1/analysis/sessions/{session_id}/tts`：按需生成临时 WAV。
- `POST /v1/live/sessions/{session_id}/tts/playback-result`：报告浏览器播放状态。
- `POST /v1/actions/{action_id}/authorization`：只授权该 Action。

原始文本、原始 WAV、完整模型请求/响应和完整回复不进入 SQLite 或审计 Payload。

## 测试与构建

```powershell
python scripts/generate_demo_music.py --check
python -m unittest discover -s tests -v
npm --prefix console run test:run
npm --prefix console run build
python -m compileall -q backend external_connector track_catalog scripts tests
```

测试使用合成输入和 Fake/Mock transport，不应被描述为真实模型、公网、扬声器或实体
空调验收。可选的 DGX 运行时验收命令见 [Phase 5 测试说明](docs/PHASE_5_TESTING.md)。

## 更多文档

- [比赛征文：让陪伴机器人先问一句](征文-让陪伴机器人先问一句.md)
- [部署到 DGX Spark](docs/DEPLOYMENT_DGX_SPARK.md)
- [网络边界](docs/NETWORK_BOUNDARIES.md)
- [Step3 与 StepAudio 适配](docs/PHASE_3_ADAPTERS.md)
- [情绪反应、策略与隐私记忆](docs/EMOTION_REACTION_MEMORY.md)
- [天气、Audius 与动作边界](docs/PHASE_4_NETWORK_ACTIONS.md)
- [控制台说明](console/README.md)
