# TG-Mirror-Bot MVP 设计文档

版本：v0.1
状态：开发中
目标：先完成稳定、可验证的 Telegram 原文搬运闭环

---

## 1. MVP 核心目标

本阶段只实现 Telegram 内容搬运的最小闭环：

```text
一个 Telegram Userbot 账号
→ 多个源频道/群组
→ 规则建立源到目标的映射
→ 历史消息按顺序补齐
→ 实时消息按顺序接收
→ 原文直接搬运到多个目标
→ 去重、重试、日志和状态可查询
```

本阶段不下载、不转码、不修改原始媒体，也不实现视频和图片加工。

---

## 2. 明确范围

### 2.1 本阶段要做

- Telegram 账号登录和 session 复用
- 多个源频道/群组的输入和解析
- 一个源可以映射到多个目标
- 多个源按全局顺序逐一处理
- 目标发送也按顺序执行
- 历史消息采集
- 实时消息监听
- 文本、图片、视频、文档等消息的原文直接搬运
- 三层去重中的数据库唯一约束和消息水位线
- 失败记录、基础重试和状态查询
- CLI 管理源、目标、路由和运行状态
- Telegram 管理 Bot，供管理员查看状态和执行常用操作
- 搬运记录群，用于接收每次投递的文字结果
- SQLite 本地运行，代码保持 PostgreSQL 兼容

### 2.2 本阶段不做

- FFmpeg 视频加工
- 水印、片头、片尾、BGM
- 图片处理
- 下载后重新上传
- Web 用户端和管理后台
- 订阅、订单和支付
- 多用户和 RBAC
- 索引机器人监听
- 消息编辑和删除同步
- 复杂相册聚合和重排
- AI 内容处理

---

## 3. 搬运语义

### 3.1 一对多

一个源可以绑定多个目标：

```text
源 A → 目标 1
     → 目标 2
     → 目标 3
```

同一条源消息会依次投递到每个已启用的目标。每个目标的投递结果独立记录，某个目标失败不能阻止其他目标执行。

### 3.2 全局串行

所有源共用一个处理队列，队列并发固定为 1：

```text
源 A 消息 1 → 目标 1 → 目标 2
源 A 消息 2 → 目标 1 → 目标 2
源 B 消息 1 → 目标 3
```

同一时刻只处理一个源消息和一个目标投递。禁止默认启动多个队列消费者，并使用跨进程运行时文件锁阻止同时启动多个搬运进程。

### 3.3 原文直接搬运

MVP 默认使用 Telegram 的转发能力实现原文搬运：

- `copy`：去掉转发来源标记，尽量表现为重新发布
- `forward`：保留原始转发来源

默认模式为 `copy`，由 `config.yaml` 控制。媒体不会在本地下载或修改。

如果 Telegram 或目标权限不允许复制，则记录错误并进入重试或失败状态，不尝试绕过限制。

---

## 4. 处理模型

### 4.1 数据对象

- `sources`：源频道/群组
- `targets`：目标频道/群组
- `routes`：源到目标的绑定关系
- `delivery_jobs`：每条源消息到每个目标的投递任务
- `sync_runs`：历史采集批次记录，可在后续阶段补充

### 4.2 投递状态

```text
pending → processing → success
                    ↘ retrying → success
                               ↘ failed
```

每条投递任务以以下组合作为幂等键：

```text
source_id + source_message_id + target_id
```

重复收到同一消息时只补发未成功的目标。

本阶段提供至少一次投递语义：正常情况下不会重复；如果进程恰好在“Telegram 已接收消息”和“数据库写入 success”之间崩溃，重启后可能出现同一条消息的重复投递。

---

## 5. 配置边界

- `.env`：API ID、API Hash、手机号等敏感配置
- `config.yaml`：运行参数、数据库、搬运模式和限速
- 数据库：源、目标、路由和投递状态

MVP 不把用户业务规则放入 YAML 热加载。

---

## 6. CLI 范围

```powershell
python main.py init-db
python main.py check-config
python main.py login
python main.py source add https://t.me/example_a https://t.me/example_b
python main.py source list
python main.py target add https://t.me/target_channel
python main.py target list
python main.py route add --source 1 --target 1 --target 2
python main.py route list
python main.py sync-history --all
python main.py run
python main.py stats
```

### 6.2 Telegram 管理 Bot

管理 Bot 使用 BotFather 创建的 Bot Token，并复用同一个 Userbot 会话解析频道和群组。管理命令包括：

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
```

只有 `.env` 中 `TG_ADMIN_IDS` 配置的管理员可以执行命令。管理 Bot 与实时搬运共享 Telegram I/O 锁和串行任务锁。

---

## 7. MVP 验收标准

1. 能登录并复用 Telegram session。
2. 能一次输入多个公开频道/群组并保存为源。
3. 一个源能绑定多个目标。
4. 启动运行后，历史消息按源顺序、按消息 ID 顺序处理。
5. 实时消息进入同一个串行队列，不产生并发发送。
6. 正常情况下，同一条源消息对每个目标只发送一次；极端崩溃窗口允许出现重复，并记录为后续优化项。
7. 单个目标失败时，其他目标仍能继续。
8. 程序重启后，未完成任务不会因为内存丢失而全部消失。
9. 能通过 CLI 查看源、目标、路由和投递统计。
10. 管理 Bot 只允许配置的管理员操作，并能查看状态、管理路由、同步历史和重试失败任务。
11. 不依赖 FFmpeg，不下载原始媒体。

---

## 8. 后续阶段

MVP 稳定后，再依次增加：

1. 视频和图片加工
2. 相册聚合、编辑和删除同步
3. 索引机器人监听
4. 多用户和配额
5. 管理后台和用户 Web
6. 订阅与支付
