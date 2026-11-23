# ThyClass 通信协议 (v1.0)

老师端与学生端之间只有两条链路：**UDP 发现** 和 **TCP 控制**。所有报文都是
UTF-8 编码的 JSON，TCP 上每行一个对象（NDJSON），单行上限 8 MB。

- UDP 发现端口：`45677`
- TCP 控制端口：`45678`（可配置）

## 1. UDP 自动发现

学生端每 1 秒向广播地址（以及 `--teacher-host` 指定的单播地址）发送 `hello`：

```json
{"t":"hello","app":"thyclass","ver":"1.0.0","name":"机房-01","room":"六年级一班","port":45678}
```

老师端收到后回一条 `teacher`，`port` 是老师端真实 TCP 端口：

```json
{"t":"teacher","app":"thyclass","ver":"1.0.0","port":45678,"room":"六年级一班","name":"老师端"}
```

学生端收到 `teacher` 后，用数据报的源 IP + `port` 建 TCP 连接。
校园网屏蔽广播时，直接配置 `student.teacher_host` 跳过发现。

## 2. TCP 控制通道

### 学生 → 老师

| `t` | 字段 | 说明 |
|---|---|---|
| `register` | `app`, `ver`, `name`, `room`, `os` | 建立连接后第一帧。`app` 必须是 `thyclass` |
| `frame` | `seq`, `mime`, `w`, `h`, `data` | 屏幕帧，JPEG 的 base64 |
| `status` | `sharing`, `locked`, `net` | 状态变化时上报；老师端据此更新列表 |
| `event` | `what`, `at`, `name` | `escape`（紧急解锁）、`screen_release`（释放本机全屏窗口）、`broadcast_exit` |
| `bye` | — | 正常退出 |

### 老师 → 学生

| `t` | 字段 | 说明 |
|---|---|---|
| `welcome` | `app`, `teacher`, `room`, `server_time` | 连接确认，`app` 固定 `thyclass` |
| `cmd` | `cmd`, 其余字段随命令 | 见下表 |
| `bcast` | `seq`, `mime`, `w`, `h`, `data` | 广播帧，JPEG 的 base64 |

`cmd` 取值：

| `cmd` | 附加字段 | 行为 |
|---|---|---|
| `broadcast_start` | `fps`, `width`, `room` | 进入全屏广播态并锁键盘 |
| `broadcast_stop` | — | 退出全屏、解锁 |
| `lock` | `on` (bool) | 单独锁定 / 解锁键盘 |
| `message` | `text` | 弹窗显示老师消息 |
| `share` | `on` (bool) | 开始 / 暂停屏幕共享 |
| `bye` | — | 要求学生端退出 |

### 帧格式

```json
{"t":"frame","seq":12,"mime":"image/jpeg","w":720,"h":450,"data":"/9j/4AAQ..."}
```

`data` 是 JPEG 的 base64 字符串；老师端只做缩略图展示，不落盘。
广播帧与学生帧结构相同，方向相反。

## 3. 时序

```
学生                                老师
  │ ── UDP hello ─────────────────►  │
  │ ◄─ UDP teacher(port) ───────────  │
  │ ── TCP connect ────────────────►  │
  │ ── register ───────────────────►  │
  │ ◄─ welcome ─────────────────────  │
  │ ◄─ cmd broadcast_start ─────────  │
  │ ◄─ bcast(seq=1..n) ─────────────  │
  │ ── status(locked=true) ────────►  │
  │ ── frame(seq=1..n) ────────────►  │
  │ ◄─ cmd broadcast_stop ──────────  │
```

## 4. 连接与容错

- 老师端对每个学生起一个读线程；写操作由内嵌锁串行化，广播帧广播给所有连接。
- 学生端断线后 2 秒重试，重新 `register`；老师端用 `name` + 来源 IP 区分设备，
  重名自动加 `-2`、`-3` 后缀。
- 单行超过 8 MB 或 JSON 非法，视为协议错误并断开该连接。
- 收到非 `thyclass` 的 `register.app` 直接拒绝。

## 5. 安全边界（v1.0 无鉴权）

协议本身**没有认证和加密**，默认信任同一局域网。请：

- 只在受控的教学网段使用，必要时用 VLAN / 防火墙限制 TCP 45678 的访问；
- 不要把端口映射到公网；
- 需要更强隔离时，在老师端前加一层 SSH 隧道或 WireGuard。

后续版本可在 `register` 中加入共享口令（HMAC 挑战应答）而不改变报文结构。
