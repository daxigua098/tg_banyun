# Telegram 内容搬运与索引监听平台 — 完整设计文档（最终整合版）

版本：v2.0 Final
状态：设计定稿
用途：交付 Codex / 开发团队直接开发

---

# 目录

1. 项目概述
2. 功能需求（完整清单）
3. 技术选型
4. 系统架构
5. 数据库设计
6. 配置设计
7. 核心模块设计
8. 视频加工设计
9. 附加内容设计
10. 索引机器人监听设计
11. 去重与可靠性设计
12. 用户系统设计
13. 订阅与计费设计
14. 权限控制设计
15. 安全与合规
16. 部署方案
17. 开发里程碑
18. 风险与对策
19. 附录（Codex 提示词 / 素材清单 / 命令清单）

---

# 1. 项目概述

## 1.1 项目名称
TG-Mirror-Bot（Telegram 内容搬运与索引监听平台）

## 1.2 项目定位
面向 Telegram 频道/群组运营者，提供：
- 多源内容自动搬运
- 视频加工（水印/片头片尾/BGM）
- 索引机器人关键词监听转发
- 用户注册 + 订阅收租的商业化能力

## 1.3 核心价值
- 自动化：多源监听 + 历史采集 + 实时更新
- 加工：视频叠加自定义内容
- 监听：索引机器人命中关键词自动转发
- 商业化：用户注册 + 按月/季/半年收租

## 1.4 商业模式
用户注册 → 购买使用时长（1/3/6/12 个月）→ 有效期内使用 → 到期续费

## 1.5 设计原则
简单优先、单机可跑、数据隔离、可维护、可扩展、可商业化

---

# 2. 功能需求（完整清单）

## 2.1 模块总览

| 模块 | 功能数 |
|------|--------|
| 源管理 | 6 |
| 历史采集 | 7 |
| 实时监听 | 6 |
| 内容过滤与处理 | 10 |
| 内容加工 | 10 |
| 去重与可靠性 | 7 |
| 索引机器人监听 | 6 |
| 用户系统与商业化 | 4 |
| 支撑功能 | 8 |
| 合计 | 64 |

## 2.2 模块 1：源管理
- F1.1 多源链接解析（t.me / @xxx / +邀请 / chat_id）
- F1.2 自动加入公开频道（限速）
- F1.3 私有链接手动加入提示
- F1.4 源状态监控（joined / error / syncing）
- F1.5 源启用/禁用
- F1.6 源优先级

## 2.3 模块 2：历史采集
- F2.1 首次接入自动采集
- F2.2 断点续传（水位线）
- F2.3 分页拉取 + 批次限速
- F2.4 采集顺序（old_to_new / new_to_old）
- F2.5 按日期过滤（since_date）
- F2.6 跳过置顶消息
- F2.7 采集统计记录

## 2.4 模块 3：实时监听
- F3.1 NewMessage 事件监听
- F3.2 Album 相册聚合
- F3.3 消息编辑同步（可选）
- F3.4 消息删除同步（可选）
- F3.5 断线自动重连
- F3.6 监听源动态增删

## 2.5 模块 4：内容过滤与处理
- F4.1 内容类型筛选（text/photo/video/document/audio/gif/sticker）
- F4.2 关键词白名单
- F4.3 关键词黑名单
- F4.4 最短文本长度
- F4.5 跳过转发消息
- F4.6 跳过纯链接
- F4.7 用户黑白名单
- F4.8 时间段控制
- F4.9 长度/大小限制
- F4.10 跨源去重

## 2.6 模块 5：内容加工
- F5.1 文字水印（九宫格）
- F5.2 图片水印 / LOGO
- F5.3 片头拼接
- F5.4 片尾拼接
- F5.5 背景音乐（保留/替换/混音）
- F5.6 附加文字（caption）
- F5.7 附加图片（相册/单独）
- F5.8 自动封面
- F5.9 自动压缩
- F5.10 自动打标签

## 2.7 模块 6：去重与可靠性
- F6.1 内存 LRU 去重
- F6.2 数据库唯一约束去重
- F6.3 水位线去重
- F6.4 失败重试队列（持久化）
- F6.5 幂等性设计
- F6.6 优雅关闭
- F6.7 状态机管理

## 2.8 模块 7：索引机器人监听
- F7.1 三种数据源（日志群 / 机器人回复 / Webhook）
- F7.2 消息解析（正则模板）
- F7.3 关键词匹配（包含/精确/正则/模糊）
- F7.4 命中转发 + 去重
- F7.5 命中统计
- F7.6 人工审核模式

## 2.9 模块 8：用户系统与商业化
- F8.1 用户注册/登录/资料
- F8.2 订阅（月/季/半年/年）
- F8.3 订单与支付
- F8.4 权限控制（RBAC）

## 2.10 支撑功能
- F9.1 日志系统（分级+轮转）
- F9.2 配置管理（YAML+热重载）
- F9.3 管理 Bot
- F9.4 统计报表
- F9.5 运行告警
- F9.6 备份/恢复
- F9.7 数据清理
- F9.8 多层限流

## 2.11 明确不做
- 多租户团队协作
- AI 内容改写
- 复杂前端框架定制
- 跨平台客户端

---

# 3. 技术选型

## 3.1 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ | |
| TG 框架 | Telethon | userbot 必须 |
| Web 后端 | FastAPI | |
| 数据库 | PostgreSQL（生产）/ SQLite（开发） | 从开始就用 PG 兼容写法 |
| ORM | SQLAlchemy 2.0 async | |
| 缓存 | Redis | 会话/限流/计数 |
| 任务 | asyncio（早期）/ Celery（后期） | |
| 视频处理 | FFmpeg + subprocess | 不引第三方封装 |
| 日志 | loguru | |
| 配置 | YAML + pydantic | |
| 前端 | Vue 3 + Element Plus + Vite | |
| 图表 | ECharts | |
| 部署 | Docker + docker-compose | |

## 3.2 关键决策
- 决策 1：必须用 Userbot（普通 Bot 无法监听别人频道）
- 决策 2：从开始就用 PostgreSQL 兼容写法
- 决策 3：所有业务表加 user_id（早期默认 1）
- 决策 4：视频加工只用 subprocess 调 ffmpeg
- 决策 5：早期 asyncio，后期再上 Celery

---

# 4. 系统架构

## 4.1 整体架构

用户浏览器 → Web 前端（Vue 3）→ API 网关（FastAPI）
  ├── 用户模块
  ├── 订阅模块
  ├── 任务模块
  └── 管理模块
→ 数据层（PostgreSQL + Redis）
→ 任务执行层（asyncio 协程组，按 user_id 隔离）
→ Telegram 账号（用户自带 / 平台账号池）

## 4.2 单机部署架构（早期）

一台服务器：
- Nginx（反向代理）
- FastAPI（后端）
- Vue 前端（静态文件）
- PostgreSQL
- Redis
- 任务进程（asyncio）

## 4.3 目录结构

tg-mirror-bot/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── core/
│   │   ├── client.py
│   │   ├── listener.py
│   │   ├── parser.py
│   │   ├── filter.py
│   │   ├── processor.py
│   │   ├── sender.py
│   │   ├── media.py
│   │   ├── video_processor.py
│   │   ├── ffmpeg_builder.py
│   │   ├── ffprobe_helper.py
│   │   ├── additional.py
│   │   ├── dedup.py
│   │   ├── source_resolver.py
│   │   ├── source_manager.py
│   │   ├── index_bot_monitor.py
│   │   ├── index_parser.py
│   │   ├── keyword_matcher.py
│   │   └── index_forwarder.py
│   ├── services/
│   │   ├── task_service.py
│   │   ├── history_service.py
│   │   ├── stats_service.py
│   │   ├── auth_service.py
│   │   ├── subscription_service.py
│   │   ├── order_service.py
│   │   └── payment_service.py
│   ├── api/
│   │   ├── auth.py
│   │   ├── sources.py
│   │   ├── targets.py
│   │   ├── rules.py
│   │   ├── logs.py
│   │   ├── stats.py
│   │   ├── subscription.py
│   │   ├── orders.py
│   │   └── admin.py
│   ├── admin/
│   └── utils/
├── frontend/
│   ├── src/
│   └── package.json
├── assets/
│   ├── intro.mp4
│   ├── outro.mp4
│   ├── bgm.mp3
│   ├── logo.png
│   ├── promo.png
│   └── fonts/
├── data/
│   ├── sessions/
│   ├── downloads/
│   ├── processed/
│   └── app.db
├── configs/
│   ├── config.yaml
│   └── rules.yaml
├── logs/
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── README.md

---

# 5. 数据库设计

## 5.1 用户相关

users（id, email, phone, username, password_hash, nickname, avatar_url, status, email_verified, phone_verified, register_ip, register_source, invited_by, created_at, last_login_at, last_login_ip）

user_login_logs（id, user_id, ip, user_agent, login_at, success, fail_reason）

user_action_logs（id, user_id, action, target_type, target_id, detail, ip, created_at）

## 5.2 订阅与订单

plans（id, code, name, duration_days, price, original_price, currency, max_sources, max_targets, max_rules, max_messages_per_month, max_history_limit, features, sort_order, is_active, created_at）

subscriptions（id, user_id, plan_id, plan_code, status, started_at, expires_at, auto_renew, source_order_id, cancelled_at, cancel_reason, created_at, updated_at）
索引：user_id, expires_at, status

orders（id, order_no, user_id, plan_id, plan_code, amount, original_amount, discount_amount, currency, payment_method, payment_id, payment_data, status, paid_at, refunded_at, refund_reason, remark, created_at, updated_at）
索引：user_id, status, order_no

usage_records（id, user_id, date, messages_processed, media_processed, storage_used_mb）
唯一：user_id + date

coupons（id, code, discount_type, discount_value, max_uses, used_count, valid_from, valid_to, is_active）

## 5.3 业务表（均加 user_id）

sources（id, user_id, tg_id, username, title, chat_type, is_private, raw_input, join_status, sync_status, last_synced_msg_id, last_sync_at, error_message, priority, enabled, created_at）

targets（id, user_id, tg_id, username, title, chat_type, enabled, created_at）

rules（id, user_id, source_id, target_id, name, enabled, allow_text, allow_photo, allow_video, allow_document, allow_audio, allow_gif, allow_sticker, keyword_whitelist, keyword_blacklist, min_text_length, max_text_length, skip_forwarded, skip_url_only, sender_blacklist, sender_whitelist, active_hours, add_signature, signature_template, replace_rules, strip_links, strip_mentions, delay_seconds, video_process_enabled, video_process_config, additional_config, created_at）

messages_log（id, user_id, source_id, source_msg_id, target_id, target_msg_id, media_group_id, content_type, status, reason, error, raw_snapshot, created_at）
唯一：user_id + source_id + source_msg_id + target_id
索引：status, source_msg, media_group

sync_history（id, user_id, source_id, started_at, finished_at, total_fetched, total_sent, total_skipped, total_failed, status, error）

index_bot_hits（id, user_id, source_group_id, source_group_title, raw_message, username, user_id_tg, query, matched_keyword, keyword_group, target_group_id, target_msg_id, status, error, created_at）

index_bot_dedup（id, user_id, user_id_tg, query_hash, keyword_group, created_at）
索引：user_id, user_id_tg, query_hash, keyword_group

---

# 6. 配置设计

## 6.1 config.yaml

telegram: api_id / api_hash / phone / session_name / proxy
behavior: forward_mode / download_media / album_aggregate / rate_limit / retry / max_media_size_mb
sources: list / auto_join / auto_join_private / join_rate_limit_seconds / history{enabled,default_limit,max_limit,batch_size,delay_between_batches,order,since_date,skip_pinned} / realtime{enabled,handle_edit,handle_delete} / history_rate_limit{messages_per_minute,media_per_minute,pause_every_n,pause_seconds}
targets: list
video_processing: enabled / ffmpeg_path / ffprobe_path / max_concurrent / timeout_seconds / fallback_on_error / text_watermark{...} / image_watermark{...} / intro{...} / outro{...} / audio{mode,bgm_path,bgm_volume,original_volume} / output{width,height,fps,video_codec,preset,crf,audio_codec,audio_bitrate}
additional: text{enabled,position,template,separator} / image{enabled,mode,image_path,caption}
index_bot_monitor: enabled / source_mode / log_group_ids / parse_patterns / keyword_groups / forward_template / dedup_window_minutes
logging: level / file / console
database: url
redis: url
jwt: secret / expire_minutes
web: host / port

（完整 YAML 见前文，可直接复制）

## 6.2 .env
TG_API_ID / TG_API_HASH / TG_PHONE / DB_PASSWORD / JWT_SECRET

---

# 7. 核心模块设计

## 7.1 模块清单
- source_resolver.py：链接解析
- source_manager.py：源管理
- listener.py：监听
- parser.py：解析
- filter.py：过滤
- processor.py：文本处理
- media.py：媒体下载上传
- sender.py：发送
- video_processor.py：视频加工
- ffmpeg_builder.py：命令拼装
- ffprobe_helper.py：视频探测
- additional.py：附加内容
- dedup.py：去重
- task_service.py：任务编排
- history_service.py：历史采集
- index_bot_monitor.py：索引机器人监听
- index_parser.py：消息解析
- keyword_matcher.py：关键词匹配
- index_forwarder.py：转发

## 7.2 处理流程

[监听数据源] → [解析] → [过滤] → [去重] → [处理] → [视频加工] → [附加内容] → [发送] → [记录]

---

# 8. 视频加工设计

## 8.1 功能
- A 文字水印（drawtext）
- B 图片水印 / LOGO（overlay）
- C 片头（concat）
- D 片尾（concat）
- E 背景音乐（keep / replace / mix）

## 8.2 技术
FFmpeg + subprocess，filter_complex 统一处理

## 8.3 输出规格
H.264 + AAC + faststart + yuv420p

## 8.4 失败回退
fallback_on_error: true → 原视频继续搬

## 8.5 关键命令模板（见前文，5 种场景）

## 8.6 中文水印
必须指定 fontfile

## 8.7 特殊情况
- 无音轨：先补静音轨
- 竖屏：scale 改 720:1280
- HEVC/AV1：强制转 H.264
- 加速：ultrafast / hwaccel

---

# 9. 附加内容设计

## 9.1 F 附加文字
拼进 caption：我们的文字 + 原 caption + 来源署名
position: top / bottom

## 9.2 G 附加图片
mode: album（相册）/ separate（单独发）/ none

## 9.3 H LOGO
mode: watermark / caption / both

## 9.4 发送模式
- 模式1：单条视频 + 图文 caption（推荐）
- 模式2：相册（视频 + 图片）
- 模式3：视频 + 单独附加消息

---

# 10. 索引机器人监听设计

## 10.1 三种数据源
- 日志群（推荐）
- 机器人回复配对
- Webhook

## 10.2 解析
正则模板，可配置多个 pattern

## 10.3 关键词匹配
contains / exact / regex / fuzzy

## 10.4 去重
(user_id_tg, query_hash, keyword_group) + dedup_window_minutes

## 10.5 转发模板
支持变量：matched_keyword / username / user_id / query / time / source_title

## 10.6 人工审核（可选）
先发审核群，管理员 ✅ 后转发

---

# 11. 去重与可靠性设计

## 11.1 三层去重
- 内存 LRU（cachetools，容量 10000）
- 数据库唯一约束
- 水位线 last_synced_msg_id

## 11.2 失败重试
持久化队列 + 启动恢复 + 最多 N 次

## 11.3 幂等性
先写 pending → 发送 → 更新 success

## 11.4 优雅关闭
捕获 SIGINT/SIGTERM，等待任务完成

## 11.5 状态机
pending → processing → success / failed → retrying → success / failed_permanent / skipped

## 11.6 多层限流
全局 / 账号 / 目标 / 源 + FloodWait 自适应

---

# 12. 用户系统设计

## 12.1 生命周期
注册 → 验证 → 试用 → 付费 → 使用 → 到期 → 续费/失效

## 12.2 认证
邮箱密码 / 手机验证码 / 微信 / Telegram / 2FA

## 12.3 安全
bcrypt / 限流 / 验证码 / 异地提醒 / JWT+Redis / 二次验证

## 12.4 防刷试用
设备指纹 + 手机号/邮箱/IP 唯一 + 人工审核

---

# 13. 订阅与计费设计

## 13.1 套餐

| 套餐 | 时长 | 价格 | 源 | 目标 | 月搬运 |
|------|------|------|-----|------|--------|
| 试用 | 3 天 | ¥0 | 1 | 1 | 100 |
| 月付 | 30 天 | ¥39 | 3 | 2 | 5000 |
| 季付 | 90 天 | ¥99 | 5 | 3 | 1万 |
| 半年付 | 180 天 | ¥179 | 10 | 5 | 3万 |
| 年付 | 365 天 | ¥299 | 20 | 10 | 10万 |
| 企业 | 定制 | 议价 | 无限 | 无限 | 无限 |

## 13.2 生命周期
生效 → 到期提醒（7/3/1 天）→ 到期 → 数据保留 30 天 → 删除

## 13.3 续费/升级/降级
- 续费：延长 expires_at
- 升级：折算剩余价值 + 补差价
- 降级：到期后生效

## 13.4 支付
- 早期：人工收款 + 后台一键开通
- 中期：支付宝 / 微信
- 后期：Stripe / USDT

## 13.5 支付安全
验签 / 幂等 / 金额校验 / 完整日志

---

# 14. 权限控制设计

## 14.1 RBAC
角色：super_admin / admin / support / user / trial
权限：source:* / target:* / rule:* / video:* / stats:* / billing:* / admin:*

## 14.2 数据隔离（关键）
所有业务表加 user_id，查询强制 WHERE user_id = current_user

## 14.3 权限表
roles / permissions / role_permissions / user_roles

---

# 15. 安全与合规

## 15.1 数据安全
session 加密（AES-256）/ 密码 bcrypt / HTTPS

## 15.2 合规文档
用户协议 / 隐私政策 / 退款政策 / 免责声明 / EULA

## 15.3 关键条款
- 用户对使用行为负责
- 不承诺不封号
- 搬运版权由用户负责
- 违规后果由用户承担

## 15.4 资质
早期个人 / 中期个体户 / 后期公司

---

# 16. 部署方案

## 16.1 开发
本地 Python + SQLite + 直接运行

## 16.2 生产
Docker + PostgreSQL + Redis + Nginx

## 16.3 服务器
- 早期 2C4G
- 中期 4C8G
- 后期 8C16G + 多节点

## 16.4 成本估算
固定 ¥300-1500/月，盈亏平衡约 13 个付费用户

---

# 17. 开发里程碑

| 阶段 | 内容 | 工作量 |
|------|------|--------|
| M1 | 登录+建库 | 1天 |
| M2 | 源解析+加入 | 1天 |
| M3 | 历史采集 | 2天 |
| M4 | 实时监听 | 1天 |
| M5 | 三层去重 | 1天 |
| M6 | 文字/图片搬运 | 2天 |
| M7 | 视频搬运 | 2天 |
| M8 | 过滤+日志+统计 | 1天 |
| M9 | 视频加工基础 | 2天 |
| M10 | 视频加工全套 | 3天 |
| M11 | 附加内容 | 1天 |
| M12 | 索引机器人监听 | 4天 |
| M13 | 用户系统 | 7天 |
| M14 | 订阅系统 | 7天 |
| M15 | 订单支付 | 10天 |
| M16 | 用户端 Web | 15天 |
| M17 | 管理后台 | 10天 |
| M18 | Telegram 账号绑定 | 7天 |
| M19 | 部署运维 | 7天 |
| M20 | 测试上线 | 15天 |
| 合计 | | 113天 |

---

# 18. 风险与对策

| 风险 | 对策 |
|------|------|
| Telegram 封号 | 用户自带账号 / 账号池轮换 / 限速 |
| FloodWait | 自动等待 + 降速 |
| 版权投诉 | 用户协议免责 + 强制标注来源 |
| 隐私合规 | 只处理公开数据 + 最小化收集 |
| 支付合规 | 早期人工 + 后期注册公司 |
| 用户数据泄露 | 加密存储 + 权限控制 |
| 恶意注册 | 设备指纹 + 人工审核 |
| 服务器攻击 | 防火墙 + 限流 + 备份 |
| 技术债务 | 现在就用 PG + user_id |
| 竞争对手 | 功能 + 服务差异化 |

---

# 19. 附录

## 19.1 给 Codex 的开发提示词

请用 Python 3.10 + Telethon + SQLAlchemy(async) + PostgreSQL + FastAPI + Vue3 开发。

核心需求：
1. userbot 监听多源，支持历史采集 + 实时更新
2. 三层去重（内存 + 数据库 + 水位线）
3. 内容类型筛选、关键词白/黑名单、用户黑白名单、时间段
4. 视频加工：文字水印 / 图片水印 / 片头 / 片尾 / BGM（subprocess 调 ffmpeg）
5. 附加内容：caption 文字 / 附加图片 / 相册模式
6. 索引机器人监听：日志群 / 机器人回复 / Webhook 三种数据源
7. 关键词匹配：contains / exact / regex / fuzzy
8. 用户系统：注册/登录/资料/2FA
9. 订阅系统：套餐/订阅/订单/支付（早期人工）
10. 权限：RBAC + 数据隔离（user_id）
11. 管理 Bot + 用户端 Web + 管理后台
12. 日志（loguru）+ 限流 + 重试 + 优雅关闭
13. 所有业务表加 user_id
14. 配置文件 config.yaml + .env，pydantic 校验

约束：
- 视频加工只用 subprocess 调 ffmpeg，不用封装库
- 所有异常捕获并记录，不崩
- 代码类型注解 + docstring 齐全
- 简单可读可维护优先
- 不做 Web 前端定制化、不做多租户、不做 AI

开发顺序：M1 → M20（见里程碑）

交付物：
- 完整可运行代码
- requirements.txt / config.yaml / rules.yaml / .env.example
- Dockerfile / docker-compose.yml
- README.md（含 ffmpeg 安装、素材准备、部署说明）

## 19.2 素材准备清单
- assets/intro.mp4
- assets/outro.mp4
- assets/bgm.mp3
- assets/logo.png
- assets/promo.png
- assets/fonts/SourceHanSans.ttf

## 19.3 命令行清单
python main.py login
python main.py run
python main.py sources
python main.py sync-history --all
python main.py stats
python main.py check-ffmpeg
python main.py process-video --input x.mp4
python main.py test-keyword "文本"
python main.py test-parse "原始消息"
python main.py index-hits --limit 50
python main.py backup
python main.py restore backup.zip

## 19.4 目录结构（见 4.3）

---

文档结束