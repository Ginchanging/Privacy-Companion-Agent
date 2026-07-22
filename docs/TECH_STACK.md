# 技术栈

本仓库只实现竞赛演示链路，不包含 Step3-VL、StepAudio 模型权重，也不修改现有模型容器。

## 运行平台与模型

| 层 | 技术 | 在本项目中的用途 |
| --- | --- | --- |
| 计算平台 | NVIDIA DGX Spark（ARM64） | 在私有 Docker 网络中运行 Demo 与既有模型服务 |
| 容器基础 | `nvcr.io/nvidia/vllm:26.06-py3` | 提供 NVIDIA/vLLM Python 运行环境 |
| 视觉与状态模型 | Step3-VL，OpenAI-compatible vLLM HTTP API | 输出严格校验的结构化状态候选和建议；不授权、不执行 |
| 语音模型 | StepAudio HTTP API | 固定合成语音 ASR、已选状态的回复措辞和 WAV TTS |

## 应用层

| 层 | 技术 | 版本/约束 |
| --- | --- | --- |
| 后端 | Python、Pydantic、Uvicorn | Python 3.11；Pydantic 2.x；Uvicorn 0.30+ |
| 媒体 | OpenCV headless、miniaudio | OpenCV 4.10+；miniaudio 1.71 |
| 前端 | React、TypeScript、Vite | React 19.2.7；TypeScript 7.0.2；Vite 8.1.5 |
| 持久化 | SQLite | 仅保存脱敏摘要、偏好、动作与审计；不保存原始音视频 |
| 部署 | Docker Compose、PowerShell、SSH loopback | DGX 不新增公网端口，Windows 浏览器经本机回环隧道访问 |

## 网络与外部服务

`external-connector` 是唯一 INTERNET 出口。Open-Meteo 天气和可选 Audius
预览请求先通过 Privacy Guard；Step3、StepAudio、SQLite 和本地音乐使用
LOCAL/LAN 路径，不经过公网连接器。Track Catalog 只保存公开 Track ID 和轮转状态，
不接收 API 凭据。

## 测试

- Python 标准库 `unittest`：后端契约、隐私、持久化、动作与端到端场景。
- Vitest：控制台 API、会话流程和浏览器媒体状态。
- TypeScript 与 Vite production build：前端类型检查和生产资源构建。

第三方组件和素材边界见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
