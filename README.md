# TG-Mirror-Bot MVP

一个按全局串行顺序运行 Telegram 原文搬运的 MVP。当前版本不做视频处理、不做图片处理，也不下载媒体文件。

## 当前能力

- 一个 Telegram Userbot 账号
- 多个源频道/群组
- 一个源绑定多个目标
- 历史消息顺序补齐
- 实时消息顺序监听
- 原文复制或转发
- 数据库幂等去重
- 失败任务持久化和基础重试
- CLI 状态查询

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

## 建立一对多路由

```powershell
python main.py route add --source 1 --target 1 --target 2
python main.py route list
```

这条路由表示：源 `1` 的每条消息依次投递到目标 `1`、目标 `2`。

## 运行

首次补齐历史消息：

```powershell
python main.py sync-history --all --limit 500
```

持续运行历史和实时监听：

```powershell
python main.py run
```

查看投递统计：

```powershell
python main.py stats
```

## 顺序保证

- 历史采集按源优先级和源 ID 顺序执行。
- 单个源的历史消息按消息 ID 从小到大处理。
- 同一消息的目标按目标 ID 顺序处理。
- 所有目标和所有源共享一个投递队列。
- MVP 强制 `transfer.worker_concurrency = 1`，配置为其他值会直接校验失败。
- `run` 和 `sync-history` 使用 `data/runtime.lock` 跨进程锁，防止启动多个搬运实例。

## 当前已知限制

- 相册会被逐条转发，后续阶段再加入相册聚合。
- 编辑和删除源消息暂不同步。
- 源消息被成功加入持久化投递队列后，水位线才会推进。
- 失败任务会在重启后继续尝试。
- 投递语义是至少一次；进程在发送成功但提交数据库前崩溃时，重启后可能重复发送。
- 不能绕过 Telegram 或目标频道的权限限制。

