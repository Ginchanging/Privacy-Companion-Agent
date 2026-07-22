# Windows 用户访问现有 DGX Spark 控制台

本文面向使用已经部署在 DGX Spark 上的竞赛 Demo 的 Windows 用户。Windows 只运行浏览器和 SSH 回环隧道；控制台静态文件、Demo Backend、SQLite、Step3、StepAudio、Track Catalog 和 external-connector 都保留在 DGX Spark。

本项目是单实例竞赛 Demo，不是带登录、租户隔离和公网入口的通用产品。只应给可信演示人员使用，并优先使用合成演示文本。

## 1. 运行结构

```text
Windows 浏览器
  -> 127.0.0.1 本地回环端口
  -> SSH 隧道
  -> DGX Demo 私有网络中的 Backend
       -> Step3 / StepAudio
       -> Track Catalog
       -> Privacy Guard -> external-connector -> INTERNET
```

DGX 不发布 Demo 主机端口。浏览器不会直接调用模型、设备或第三方互联网 API。

## 2. Windows 需要什么

仅访问现有部署时需要：

- Windows 10 或 Windows 11；
- Windows PowerShell 5.1 或 PowerShell 7；
- Windows OpenSSH Client；
- Edge、Chrome 或其他现代浏览器；
- 管理员单独提供的 SSH 账号、密钥和 SSH 别名配置；
- 本仓库的 `scripts/start_dgx_console_tunnel.ps1`。

不需要在 Windows 安装：

- Python；
- Node.js 或 npm；
- Docker；
- Step3 或 StepAudio；
- Backend、SQLite、Track Catalog 或 external-connector；
- Audius、天气或模型凭据。

## 3. 管理员需要提前提供什么

管理员应通过安全渠道分别提供：

1. DGX SSH 主机名或地址；
2. 独立 SSH 用户名；
3. 该用户自己的 SSH 私钥；
4. 建议使用的 SSH 别名；
5. `start_dgx_console_tunnel.ps1` 脚本或只包含该脚本的访问包；
6. 是否允许批准音乐动作，以及声音会从哪台设备发出。

不要通过 Git、聊天截图、邮件正文或本说明分发真实私钥、密码、Token、完整公网地址或 `.env`。

### 当前权限限制

当前隧道脚本会通过 SSH 执行远端 `docker ps` 和 `docker inspect`，用来动态找到 Backend 的 Demo 私有网络地址。因此 SSH 用户必须能够无 `sudo` 执行这两个查询。

Docker 访问通常等同于较高的宿主机权限。不要仅为了访问控制台而给不可信用户加入 Docker 用户组。当前方案适合可信演示人员；普通访客或公开访问需要单独实现受限网关，不属于当前 Demo。

## 4. 准备 Windows

### 4.1 检查 PowerShell 和 OpenSSH

打开 PowerShell：

```powershell
$PSVersionTable.PSVersion
Get-Command ssh.exe
ssh -V
```

如果找不到 `ssh.exe`，在 Windows“设置 → 系统 → 可选功能”中安装“OpenSSH 客户端”。

### 4.2 放置访问脚本

推荐目录：

```text
C:\SparkConsoleAccess\
└─ scripts\
   └─ start_dgx_console_tunnel.ps1
```

也可以复制完整仓库，但普通使用者不应运行部署、回滚或模型管理脚本。

### 4.3 配置个人 SSH 别名

编辑当前用户的：

```text
%USERPROFILE%\.ssh\config
```

使用管理员提供的值替换所有占位符：

```sshconfig
Host your-dgx-alias
    HostName <管理员提供的主机名或地址>
    User <管理员分配的用户名>
    IdentityFile C:/Users/<当前Windows用户名>/.ssh/<个人私钥文件>
    IdentitiesOnly yes
```

`Host` 别名只能包含字母、数字、点、下划线或连字符。不要把真实配置提交到仓库。

### 4.4 验证 SSH 和查询权限

```powershell
$DgxAlias = "your-dgx-alias"

ssh -o BatchMode=yes -o ConnectTimeout=10 $DgxAlias "echo connected"

ssh -o BatchMode=yes -o ConnectTimeout=10 $DgxAlias `
    "docker ps --filter label=com.docker.compose.project=spark-active-companion-demo --filter label=com.docker.compose.service=backend --format '{{.Names}}|{{.Status}}'"
```

预期结果：

- 第一条命令输出 `connected`；
- 第二条命令只返回一个正在运行且健康的 Backend；
- 不应要求交互输入密码；
- 不要执行 `docker stop`、`docker restart`、`docker compose down` 或任何 prune 命令。

## 5. 启动控制台

```powershell
cd C:\SparkConsoleAccess

$DgxAlias = "your-dgx-alias"

$Tunnel = .\scripts\start_dgx_console_tunnel.ps1 `
    -SshAlias $DgxAlias `
    -LocalPort 8000

$Tunnel | Format-List
```

正常会返回：

```text
process_id           : <本次SSH进程号>
local_url            : http://127.0.0.1:8000/console/
local_port           : 8000
remote_published_port: 空
```

打开返回的地址：

```powershell
Start-Process $Tunnel.local_url
```

如果脚本被当前 PowerShell 执行策略阻止，可只为当前窗口临时放行，然后重试：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

不要修改计算机级或用户级执行策略。

### 本机端口已被占用

改用其他回环端口，例如：

```powershell
$Tunnel = .\scripts\start_dgx_console_tunnel.ps1 `
    -SshAlias $DgxAlias `
    -LocalPort 18080
```

随后打开脚本返回的 `local_url`，不要自行猜测地址。

## 6. 连接后验证

```powershell
$BaseUrl = "http://127.0.0.1:$($Tunnel.local_port)"

Invoke-RestMethod "$BaseUrl/health"

Invoke-RestMethod "$BaseUrl/v1/live/health" |
    ConvertTo-Json -Depth 8
```

应重点检查：

- `deployment.backend` 为 `DGX_SPARK`；
- `deployment.console_access` 为 `SSH_LOOPBACK`；
- Step3 和 StepAudio 显示可达状态；
- `raw_media_persisted` 为 `false`；
- 浏览器地址始终是 `127.0.0.1`，而不是 DGX 公网地址。

健康状态只证明服务可达，不等于本次已经完成模型推理、语音合成、音乐播放或物理动作。健康检查不会为了检查 Audius 而访问互联网。

## 7. 控制台怎么操作

### 7.1 推荐主流程：文本对话

1. 打开顶部“对话”。
2. 在“演示文本”输入合成示例，例如“今天项目终于完成了，我特别开心”。
3. 点击“分析并发送”，等待 Step3 返回候选状态和初步回复。
4. 点击“继续这次对话”。继续时使用 `analysis_id`，不会重新发送原始文本；后端直接选择最高置信度状态，不再要求确认情绪状态。
5. 查看最终回复和确定性策略结果。
6. 如果出现音乐或空调动作，分别批准或拒绝。批准音乐后，DGX 会准备音频并通过当前 SSH 回环交给 Windows 浏览器；若浏览器阻止自动播放，必须再点击“点击播放”。没有这次点击或真实 `playing` 事件，后端不会把音乐标记为成功，也不会继续执行后续动作。
7. 音乐卡显示“浏览器已开始播放”只代表浏览器接受了播放，不代表已确认扬声器可听。需要时还可点击“播放这段回复”调用 StepAudio TTS；语音失败时保持纯文本。
8. 切换到“审计”核对真实后端事件、网络边界、外发数据和授权结果。
9. 完成后点击“重置本轮”。

### 7.2 审计页面怎么看

- 感知区：输入来源、人物检测和适配器状态；
- 交互与判断：Step3 候选、最高置信度选择、动作授权和执行结果；
- 环境与记忆：天气来源、已确认偏好和脱敏摘要；
- 动作卡片：音乐和空调各自的授权及执行状态；
- 隐私网关：实际外发 JSON 和被拒绝字段；
- 时间线：真实后端事件、延迟、网络范围、会话和动作编号。

### 7.3 演示场景

“演示场景”中可以使用：

- 启动真实/降级链；
- 模拟人物回家；
- 天气失败；
- Step3 超时；
- 语音识别失败；
- 隐私违规。

纯模拟场景不能称为真实模型、真实摄像头、真实天气或物理设备成功。

## 8. 使用边界和多人使用注意事项

- 只输入合成 Demo 文本，不输入真实敏感对话、真实音频或真实视频；
- Step3 只提供候选和建议，不能授权或执行动作；
- 音乐和空调必须分别授权；
- 空调始终是 Mock，不会控制实体空调；
- 音乐动作可能从 DGX 所在设备发声，而不是当前 Windows 电脑，批准前先与管理员确认；
- TTS 音频由浏览器临时播放，不写入 SQLite；
- 当前部署没有用户登录或租户隔离；用户偏好和脱敏摘要由同一个 Demo Backend 管理；
- “重置本轮”只关闭当前会话，不会清除共享的用户偏好或脱敏摘要；
- 只有指定演示管理员可以修改或清除共享偏好和摘要，普通演示人员不要操作这些管理按钮；
- 多名演示人员应错峰使用，并在每轮结束后重置当前会话；
- 待授权动作在服务重启后不会自动执行。

## 9. 安全停止

只停止本次脚本返回的 SSH 进程：

```powershell
Stop-Process -Id $Tunnel.process_id
```

可验证本地端口已经关闭：

```powershell
Get-NetTCPConnection `
    -LocalAddress 127.0.0.1 `
    -LocalPort $Tunnel.local_port `
    -State Listen `
    -ErrorAction SilentlyContinue
```

没有输出表示该监听已经关闭。

不要使用：

```text
Stop-Process -Name ssh
taskkill /IM ssh.exe
killall ssh
```

这些命令可能误关其他 SSH 会话。

## 10. 常见问题

| 现象 | 处理方法 |
| --- | --- |
| `ssh.exe` 不存在 | 安装 Windows OpenSSH Client |
| SSH 要求密码或返回权限错误 | 检查个人密钥和 SSH 别名，联系管理员；不要把密码写入脚本 |
| `Could not inspect` | 当前 SSH 用户没有所需 Docker 查询权限，联系管理员 |
| `Exactly one running ... backend` | Backend 不存在或存在多个实例；停止操作并联系管理员，不要自行重启容器 |
| 本地端口已被占用 | 改用 `-LocalPort 18080` 等未使用端口 |
| 页面打不开 | 确认 `$Tunnel` 进程仍在、使用脚本返回的 URL，并检查 `/health` |
| 页面仍显示旧样式 | 按 `Ctrl+F5` 强制刷新；仍不正确时把静态资源文件名告知管理员 |
| Step3/StepAudio 离线 | 只记录并联系管理员，不要重启模型服务 |
| TTS 返回纯文本 | 保留文字结果；不要声称语音播放成功 |
| 天气来源为缓存或固定演示 | 不要声称真实天气 API 成功 |

## 11. 管理员交付检查表

- [ ] DGX 上 Backend、Track Catalog、external-connector 均健康；
- [ ] Step3、StepAudio 可达且未为本次访问重启；
- [ ] 没有发布新的 DGX 主机端口；
- [ ] 为使用者分配独立 SSH 账号和独立密钥；
- [ ] 使用者属于可信演示人员，并了解当前 Docker 查询权限风险；
- [ ] 通过安全渠道提供 SSH 配置值，不写入访问包；
- [ ] 访问包只包含隧道脚本和本说明，不包含 `.env`、数据库、Token 或私钥；
- [ ] 告知使用者音乐可能发声，空调始终为 Mock；
- [ ] 安排单用户或错峰演示；
- [ ] 使用结束后确认只关闭对应的本地 SSH 隧道。

如需部署或回滚 DGX 服务，应由管理员使用 [DGX Spark 部署说明](DEPLOYMENT_DGX_SPARK.md)，普通控制台用户不应执行这些操作。
