# TG-Mirror-Bot MVP

一个按全局串行顺序运行 Telegram 原文搬运的 MVP。当前版本不做视频处理、不做图片处理，也不下载媒体文件。

## 当前能力

- 一个 Telegram Userbot 账号
- 多个源频道/群组
- 一个源绑定多个目标
- 历史消息顺序补齐
- 实时消息顺序监听
- 多图相册聚合搬运
- 原文复制或转发
- 数据库幂等去重
- 失败任务持久化和基础重试
- CLI 状态查询
- Telegram 管理 Bot

详细范围见 `MVP设计文档.md`。

## 安装

要求 Python 3.10+。当前开发环境已使用 Python 3.13 验证语法。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`：

```dotenv
TG_API_ID=你的_api_id
TG_API_HASH=你的_api_hash
TG_PHONE=+8613800000000
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
```

不要提交 `.env` 或 `*.session` 文件。

## 初始化

```powershell
python main.py check-config
python main.py init-db
python main.py login
```

首次登录可能需要在终端输入 Telegram 验证码和二次验证密码。

## 配置源和目标

```powershell
python main.py source add https://t.me/channel_a https://t.me/channel_b
python main.py source list

python main.py target add https://t.me/target_a https://t.me/target_b
python main.py target list
```

私有邀请链接需要显式允许 Userbot 加入：

```powershell
python main.py source add "https://t.me/+invite_hash" --join
```

如果 Userbot 已经加入私有目标频道，也可以直接添加为目标：

```powershell
python main.py target add "https://t.me/+private_target_invite"
```

目标添加不会自动加入私有频道；Userbot 必须先加入，并且具备发消息权限。

## 建立一对多路由

```powershell
python main.py route add --source 1 --target 1 --target 2
python main.py route list
```

这条路由表示：源 `1` 的每条消息依次投递到目标 `1`、目标 `2`。

## 内容过滤

当前配置只允许图片和视频进入投递队列：

```yaml
content_filter:
  media_only: true
  allow_photo: true
  allow_video: true
```

启用后，纯文本、群员聊天、网页预览、投票、表情和系统消息都会被过滤，不会发送到目标群。

## 搬运记录群

可以指定一个或多个 Telegram 群组接收每次投递的文字记录。Userbot 必须先加入私有群，或者使用 `--join`：

```powershell
python main.py record add --join "https://t.me/+record_group_invite"
python main.py record list
```

记录内容包括投递状态、源、源消息 ID、目标、目标消息 ID、尝试次数和错误信息。记录发送失败不会影响正常搬运。

## 运行

首次补齐历史消息：

```powershell
python main.py sync-history --all --limit 500
```

持续运行历史和实时监听：

```powershell
python main.py run
```

如果已经手动执行过历史同步，只希望启动后监听新消息：

```powershell
python main.py run --skip-history
```

查看投递统计：

```powershell
python main.py stats
```

## Telegram 管理 Bot

管理 Bot 是可选功能。它复用同一个 Userbot 登录会话和数据库，因此配置后只需要运行主程序。

### 1. 创建 Bot

在 Telegram 中找到 `@BotFather`，使用 `/newbot` 创建一个 Bot，并保存 Bot Token。

### 2. 配置 `.env`

```dotenv
TG_BOT_TOKEN=123456:replace-with-botfather-token
TG_ADMIN_IDS=你的Telegram用户ID
TG_BOT_SESSION_NAME=data/sessions/management_bot
```

多个管理员用英文逗号分隔：

```dotenv
TG_ADMIN_IDS=123456789,987654321
```

`TG_ADMIN_IDS` 是 Telegram 用户 ID，不是用户名。执行 `python main.py login` 时会显示当前账号的用户 ID。

### 3. 启用管理 Bot

编辑 `configs/config.yaml`：

```yaml
management_bot:
  enabled: true
```

然后启动主程序：

```powershell
python main.py run
```

如果已经手动执行过历史同步，只希望启动后监听新消息：

```powershell
python main.py run --skip-history
```

程序会同时启动：

- Userbot 监控和搬运
- 管理 Bot 命令处理

如果只想调试管理 Bot，可以运行：

```powershell
python main.py bot
```

管理 Bot 支持以下命令：

```text
/status
/sources
/targets
/routes
/stats
/jobs [status] [数量]
/sync <源ID|all> [数量]
/retry_failed [任务ID]
/source_add [--join] <频道/群组> [...]
/target_add <频道/群组> [...]
/source_enable <源ID> [...]
/source_disable <源ID> [...]
/target_enable <目标ID> [...]
/target_disable <目标ID> [...]
/route_add <源ID> <目标ID> [...]
/route_delete <源ID> <目标ID>
/record_add [--join] <群组> [...]
/records
/help
```

只有 `TG_ADMIN_IDS` 中的用户可以执行管理命令。

## 顺序保证

- 历史采集按源优先级和源 ID 顺序执行。
- 单个源的历史消息按消息 ID 从小到大处理。
- 同一消息的目标按目标 ID 顺序处理。
- 所有目标和所有源共享一个投递队列。
- MVP 强制 `transfer.worker_concurrency = 1`，配置为其他值会直接校验失败。
- `run`、`bot` 和 `sync-history` 使用 `data/runtime.lock` 跨进程锁，防止启动多个搬运实例。
- 管理 Bot 和主搬运流程共享 Telegram I/O 锁，以及同一条串行投递队列。

## 当前已知限制

- 相册会按 Telegram 的 grouped_id 聚合后一次性投递。
- 编辑和删除源消息暂不同步。
- 源消息被成功加入持久化投递队列后，水位线才会推进。
- 失败任务会在重启后继续尝试。
- 投递语义是至少一次；进程在发送成功但提交数据库前崩溃时，重启后可能重复发送。
- 管理 Bot 当前是文本命令界面，没有 Inline Keyboard 和审核流程。
- 不能绕过 Telegram 或目标频道的权限限制。
