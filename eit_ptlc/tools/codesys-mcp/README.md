# inoproshop-codesys-mcp

常驻热实例 MCP server, 让 AI 直接读/写/编译汇川 InoProShop(CODESYS) 工程里的 **单个 POU**,
全程不触碰 3.7MB 的 `.project` 二进制, 也不导出 4.9MB 整工程 XML.

## 为什么自建, 不用现成的 `@codesys/mcp-toolkit`

现成 toolkit 面向 CODESYS 3.5 **SP21**; 本机 InoProShop V1.9.1.6 内核是 **3.5.11.10 (SP11)**.
实测 toolkit 在 SP11 上三处不可用(均已验证):

| 假设(SP21) | SP11 实况(实测) |
|---|---|
| 命令行 `--noUI` | `projects.open` 在 `--noUI` 下 **NPE**, 必须 **带 UI** 才能开工程 |
| 结果走子进程 **stdout**(`SCRIPT_SUCCESS` marker) | UI 模式下脚本 `print` **到不了 stdout**(进了 IDE 消息窗) |
| `--noUI` 退出后自动结束 | UI 模式不会自动结束, 需脚本 `system.exit()` |

因此本实现走 SP11 原生路线: **带 UI 常驻 + 文件 IPC**.

## 架构

```
Claude Code ──stdio──► server.mjs (Node MCP)
                          │  懒启动一次, 保持热
                          ▼
                 InoProShop.exe --profile=... --runscript=worker_active.py   (带 UI 窗口)
                          │  worker_body.py 常驻循环: 打开工程 -> 轮询 requests/ -> 写 responses/
                          ▼
              文件 IPC: <ipc>/requests/<id>.req.json  ⇄  <ipc>/responses/<id>.resp.json
```

- 请求/响应均为原子写(`.tmp` + rename); 响应用 ASCII-escaped JSON, 中文经 `\uXXXX` 无损往返.
- worker 用 `system.process_messageloop()` 泵 UI 事件, 保持 IDE 响应.
- 首次工具调用冷启动 InoProShop ~14s; 之后 status/read ~200ms, list ~1.4s, compile ~14s.
- `worker.status` 带 project、PLC IP、协议版本 v3、worker body SHA-256 和进程实例 ID；任一不匹配时客户端拒绝 attach，
  必须受控重启，不能静默复用错误工程或历史活动通信路径。

## 完整下载安全边界

MCP 不直接暴露 deploy 工具。完整下载只能由上位机安全入口发起，并同时满足：

- Python、Node 和 worker 共用持久 `deploy.guard.json`；部署事务期间 MCP 的写、保存、编译、
  生成代码和 shutdown 都会失败关闭。
- deploy 请求携带 60 秒一次性票据，绑定 worker 实例、PLC 握手提交序号、工程 SHA-256、目标
  PLC IP、协议版本和 worker body SHA-256。worker 必须原子 claim 请求并 consume 票据，重启后不重放任何遗留 claim。
- worker 在 `deploy.physical.lock` 临界区内重新按明确 IP 设路径、创建在线句柄并回读目标，随后
  再核验票据/守卫/有效期/工程 SHA；哈希、目标或 worker 构建不符时
  `login` 调用次数必须为零。
- Host 只能在物理锁不存在时清除 deploy guard；人工对账也不得夺取活进程或不可读的物理锁，
  仅能归档具有完整 owner token 且 owner PID 已死亡的遗留锁。
- guard 释放使用 `active → releasing → 删除自身物理屏障 → 删除 guard` 两阶段协议；任一步失败都
  保留 fail-closed 标记。`last-cleared` / `last-reconciled` 完成审计只在实际删除确认后写入。
- 请求超时只撤销尚未 claim/consume 的内容；已经认领则结果视为不明确，禁止自动重试。
- `codesys_shutdown` 不再超时强杀 InoProShop；活动部署守卫存在时直接拒绝。

## 已验证的 SP11 脚本 API(真源)

| 操作 | 调用 |
|---|---|
| 打开 | `projects.open(path, u"", True)` (path, password, primary) |
| 定位 | `proj.find(name, True)` / 按路径 `Application/Folder/POU` |
| 读 | `pou.textual_declaration.text` / `pou.textual_implementation.text` |
| 写 | `pou.textual_implementation.replace(text)`(整体替换) |
| 编译 | `proj.active_application.build()` |
| 离线生成代码/符号 XML | `proj.active_application.generate_code()` |
| 取编译错误 | `system.get_message_objects("97f48d64-a2a3-4856-b640-75c046e37ea9")` 的 `.severity`/`.text` |
| 保存 | `proj.save()` |

完整 API 参考: `D:\InoProShop\CODESYS\Online Help\ScriptEngine.chm`.

## MCP 工具

| 工具 | 说明 |
|---|---|
| `codesys_status` | 查询 worker/工程状态(并懒启动 InoProShop) |
| `codesys_list_pous` | 列出 Application 下可编辑 POU 的路径 |
| `codesys_read_pou` | 读某 POU 的声明(VAR)+实现(ST) |
| `codesys_write_pou` | 写某 POU 的声明/实现(整体替换; `save` 控制是否落盘) |
| `codesys_caps` | 只读探针: 列出某对象暴露的 ScriptEngine 成员名 |
| `codesys_create_object` | 在已有 POU 下新建 Action(或 Application 下新建 POU); 幂等 |
| `codesys_compile` | build 并返回错误/警告 |
| `codesys_generate_code` | 离线生成 Symbol Configuration XML（不登录/不下载 PLC） |
| `codesys_save` | `proj.save()` 落盘 |
| `codesys_shutdown` | 停 worker, 关 InoProShop |

**写入语义**: `save=false`(默认)只改内存中的工程, 关闭 IDE 即丢弃, `.project` 文件不变;
只有 `save=true` 或单独调 `codesys_save` 才落盘. 建议先 `save=false` + `codesys_compile` 验证, 再保存.

**新建对象**: `codesys_create_object` 建出的是空壳, 正文要随后用 `codesys_write_pou` 写。
新增一个 L2 原子动作的完整顺序是 `create_object` → `write_pou`(动作正文) → `write_pou`(派发器
`CASE` 加动作码) → `compile` → `save`。`create` 与 `write` 同属写类 op: 走 `EXCLUSIVE_OPS`
写锁 + 会话属主门, 且在部署事务窗口内被 deploy guard 挡住(三处 op 集合在
`worker_body.py` / `server.mjs` / `driver/codesys_ipc.py` 是跨语言镜像, 改一处要同改三处)。

⚠ **改了 `worker_body.py` 必须重启 MCP host**: server.mjs 与 codesys_ipc.py 都在启动时把
worker_body.py 的 sha256 钉死, 文件一变, 存活 worker 报 fingerprint mismatch、新 worker 拒绝
spawn。正确顺序是**先** `codesys_shutdown` 停掉 worker, **再**改文件, 然后重连 MCP。

## 接入 Claude Code

仓库根 `.mcp.json` 已注册名为 `codesys` 的 server. 首次需在 Claude Code 内批准该项目级 MCP server
(或 `/mcp` 重连 / 重启会话). 配置可用 CLI flag / 环境变量覆盖:
`--exe / INOPROSHOP_EXE`, `--profile / INOPROSHOP_PROFILE`, `--project / CODESYS_PROJECT`, `--ipc / CODESYS_IPC_DIR`.

> 注意: 激活后首次调用会弹出并常驻一个 **InoProShop 窗口**(SP11 必须带 UI)。MCP server
> 退出不会自动关闭共享 worker；仅显式 `codesys_shutdown` 或配置的空闲超时会关闭，且活动部署
> 事务期间 shutdown 被拒绝。期间请勿在另一个交互式 InoProShop 里打开同一工程。

## 自测(不依赖 Claude Code)

```bash
cd eit_ptlc/tools/codesys-mcp
npm install
node test_worker.mjs   # 直接文件 IPC 测 worker(status/list/read/compile)
node test_mcp.mjs      # 经 MCP SDK client 端到端测 server.mjs(含安全的内存写探针+还原)
node server.mjs --selftest  # 文件锁/停止/接管/指纹协议的离线自测，不启动 PLC 下载
```
