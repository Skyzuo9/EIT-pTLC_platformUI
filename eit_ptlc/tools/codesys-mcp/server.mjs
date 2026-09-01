#!/usr/bin/env node
/**
 * 功能:
 *   常驻热实例 MCP server. 懒启动一个带 UI 的 InoProShop(CODESYS SP11) 实例并保持热,
 *   其中跑 worker_body.py 常驻 worker. 每个 MCP 工具调用经"请求/响应文件"与 worker 通信,
 *   实现亚秒级的 POU 读/写/编译/保存, 全程不触碰 4.9MB XML, 也不依赖 stdout(SP11 UI 下不可用).
 * 配置(优先级: CLI flag > env > 默认):
 *   --exe / INOPROSHOP_EXE        InoProShop.exe 路径
 *   --profile / INOPROSHOP_PROFILE  CODESYS profile 名
 *   --project / CODESYS_PROJECT     .project 工程路径
 *   --ipc / CODESYS_IPC_DIR         文件 IPC 目录(默认 <此目录>/ipc)
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { spawn, spawnSync } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WORKER_BODY_PATH = path.join(__dirname, "worker_body.py");
const WORKER_BODY_SHA256 = crypto.createHash("sha256")
  .update(await fs.readFile(WORKER_BODY_PATH))
  .digest("hex");

// ---------- 配置 ----------
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    // 允许连字符/数字的长 flag(如 --session-idle-release); 既有单词 flag 不受影响
    const m = /^--([a-zA-Z][a-zA-Z0-9-]*)(?:=(.*))?$/.exec(a);
    if (m) out[m[1]] = m[2] !== undefined ? m[2] : argv[++i];
  }
  return out;
}
const A = parseArgs(process.argv.slice(2));
const CFG = {
  exe: A.exe || process.env.INOPROSHOP_EXE || "D:\\InoProShop\\CODESYS\\Common\\InoProShop.exe",
  profile: A.profile || process.env.INOPROSHOP_PROFILE || "InoProShop(V1.9.1.6)",
  project: A.project || process.env.CODESYS_PROJECT || path.resolve(__dirname, "../../plc/20260702.project"),
  ipcDir: A.ipc || process.env.CODESYS_IPC_DIR || path.join(__dirname, "ipc"),
  compileCategory: "97f48d64-a2a3-4856-b640-75c046e37ea9",
  pollSec: A.poll ? Number(A.poll) : 0.12,
  // PLC IP: 注入 worker 供 op_deploy 按 IP 单播设活动路径; 与后端共用同一 worker 时必须注入(否则后端 deploy 缺 IP)
  plcIp: A.plcip || process.env.CODESYS_PLC_IP || "",
  // 空闲超时(秒): worker 无请求超过该时长即关闭 InoProShop 释放工程锁
  idleSec: A.idle ? Number(A.idle) : 120,
  // 会话属主租约阈值(秒); 与 codesys_ipc._SESSION_* / app.yaml codesys.session_* 必须同值(跨语言镜像)
  sessionIdleReleaseSec: A["session-idle-release"] ? Number(A["session-idle-release"]) : 60,
  sessionWaitTimeoutSec: A["session-wait-timeout"] ? Number(A["session-wait-timeout"]) : 300,
  sessionMaxHoldSec: A["session-max-hold"] ? Number(A["session-max-hold"]) : 900,
};
const REQ_DIR = path.join(CFG.ipcDir, "requests");
const RESP_DIR = path.join(CFG.ipcDir, "responses");
const STATUS_PATH = path.join(CFG.ipcDir, "worker.status");
const STOP_PATH = path.join(CFG.ipcDir, "worker.stop");
const WORKER_SCRIPT = path.join(CFG.ipcDir, "worker_active.py");
const SPAWN_LOCK_PATH = path.join(CFG.ipcDir, "spawn.lock");   // 跨进程冷启动互斥
const WRITE_LOCK_PATH = path.join(CFG.ipcDir, "write.lock");   // 单写者租约
const SESSION_OWNER_PATH = path.join(CFG.ipcDir, "session.owner");  // 可抢占会话属主租约
const SESSION_CONTROL_PATH = path.join(CFG.ipcDir, "session_control.json");
const LEASE_PATH = path.join(CFG.ipcDir, "lease.status");
const DEPLOY_GUARD_PATH = path.join(CFG.ipcDir, "deploy.guard.json");
const WORKER_PROTOCOL_VERSION = 3;
const DEPLOY_AUTH_TTL_SEC = 60;
const DEPLOY_GUARD_BLOCKED_OPS = new Set([
  "write", "create", "save", "compile", "generate_code", "deploy", "shutdown",
  "takeover", "release_takeover", "stop", "start_worker", "restore",
]);

const log = (...a) => process.stderr.write("[codesys-mcp] " + a.join(" ") + "\n");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function safeUnlink(p) { try { await fs.unlink(p); } catch {} }
async function readJson(p) {
  // 剥 BOM: PowerShell/记事本手改的 session_control.json 常带 U+FEFF; 机器写入的无 BOM 文件
  // 零行为变化 (与 worker_body.read_json_file / codesys_ipc._read_json(utf-8-sig) 同语义镜像)
  return JSON.parse((await fs.readFile(p, "utf8")).replace(/^\ufeff/, ""));
}
async function writeJsonAtomic(p, obj) {
  const tmp = p + ".tmp";
  await fs.mkdir(path.dirname(p), { recursive: true });
  await fs.writeFile(tmp, JSON.stringify(obj, null, 2), "utf8");
  await fs.rename(tmp, p);
}
async function removeLockIfOwned(lockPath, ownerToken) {
  if (!ownerToken) return false;
  let held = null;
  try { held = await readJson(lockPath); } catch { return false; }
  if (!held || held.owner_token !== ownerToken) return false;
  try { await fs.unlink(lockPath); return true; } catch { return false; }
}
const canonicalProject = (p) => path.resolve(p).toLowerCase();
async function readDeployGuard() {
  try { return await readJson(DEPLOY_GUARD_PATH); }
  catch {
    try { await fs.access(DEPLOY_GUARD_PATH); return { state: "corrupt", purpose: "unreadable" }; }
    catch { return null; }
  }
}
async function assertDeployGuardAllows(op) {
  const guard = await readDeployGuard();
  if (!guard) return;
  if (DEPLOY_GUARD_BLOCKED_OPS.has(op)) {
    throw new Error(`PLC project/deploy transaction is active (${guard.purpose || "unknown"}); operation '${op}' is blocked`);
  }
}
// 接管标志 TTL 逃生阀(F8): manual_control=true 且 updated_at(epoch 秒) 距今超过该时长 → 视为
// 过期(未接管)+告警。缺 updated_at 的旧格式 = 永不过期(人类属主, 禁按 pid 存活自动失效)。
// 与 worker_body.py / codesys_ipc.py 的 MANUAL_CONTROL_TTL_SEC 同值(秒)。
const MANUAL_CONTROL_TTL_SEC = 86400;
async function readControl() {
  try { return await readJson(SESSION_CONTROL_PATH); } catch { return {}; }
}
async function assertNotManualControl(op) {
  if (op === "status") return;
  const control = await readControl();
  if (!control || !control.manual_control) return;
  if (control.updated_at !== undefined && control.updated_at !== null) {
    const ageSec = Date.now() / 1000 - Number(control.updated_at);   // updated_at 为 epoch 秒(时间戳契约)
    if (Number.isFinite(ageSec) && ageSec > MANUAL_CONTROL_TTL_SEC) {
      log(`manual_control 标志已过期(${(ageSec / 3600).toFixed(1)}h > TTL 24h), 视为未接管放行 op=${op}`);
      return;
    }
  }
  const owner = control.owner || "operator";
  const reason = control.reason || "manual control";
  throw new Error(`PLC session is under manual control by ${owner}; operation '${op}' is blocked (${reason})`);
}
async function beginLease(op) {
  await writeJsonAtomic(LEASE_PATH, {
    state: "active",
    owner: "mcp",
    op,
    pid: process.pid,
    started_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
  });
}
async function endLease(op) {
  let previous = {};
  try { previous = await readJson(LEASE_PATH); } catch {}
  await writeJsonAtomic(LEASE_PATH, {
    state: "idle",
    owner: previous.owner || "mcp",
    last_op: op,
    pid: process.pid,
    started_at: previous.started_at,
    ended_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
  });
}

// ---------- worker 生命周期 ----------
let workerChild = null;
let startLock = null;
let spawnLockToken = null;

async function readStatus() { try { return await readJson(STATUS_PATH); } catch { return null; } }

// 判定 pid 进程是否存活: kill(pid,0) 不发信号只探测, ESRCH=不存在, EPERM=存在但无权(仍算活)
function pidAlive(pid) {
  if (!pid || pid <= 0) return false;
  try { process.kill(pid, 0); return true; }
  catch (e) { return e.code === "EPERM"; }
}

async function buildWorkerScript() {
  const bodyBytes = await fs.readFile(WORKER_BODY_PATH);
  const currentBodySha256 = crypto.createHash("sha256").update(bodyBytes).digest("hex");
  if (currentBodySha256 !== WORKER_BODY_SHA256) {
    throw new Error("worker_body.py changed after this MCP host started; restart the MCP host before spawning CODESYS");
  }
  const body = bodyBytes.toString("utf8");
  const header =
    "# -*- coding: utf-8 -*-\n" +
    `IPC_DIR = r"${CFG.ipcDir}"\n` +
    `PROJECT_PATH = r"${CFG.project}"\n` +
    `POLL_SEC = ${CFG.pollSec}\n` +
    `COMPILE_CATEGORY = "${CFG.compileCategory}"\n` +
    `PLC_IP = r"${CFG.plcIp}"\n` +
    `IDLE_TIMEOUT_SEC = ${CFG.idleSec}\n` +
    `WORKER_PROTOCOL_VERSION = ${WORKER_PROTOCOL_VERSION}\n` +
    `DEPLOY_AUTH_TTL_SEC = ${DEPLOY_AUTH_TTL_SEC}\n` +
    `WORKER_BODY_SHA256 = "${WORKER_BODY_SHA256}"\n\n`;
  await fs.writeFile(WORKER_SCRIPT, header + body, "utf8");
}

// 活体探测: status 存在且其 pid 存活(不论 state)返回 status, 否则 null
// — 与 codesys_ipc.py _read_live_status 同语义(跨语言镜像)
async function readLiveStatus() {
  const s = await readStatus();
  if (!s || !pidAlive(s.pid)) return null;
  const problems = [];
  if (canonicalProject(s.project || "") !== canonicalProject(CFG.project)) problems.push(`project=${s.project}`);
  if (String(s.plc_ip || "") !== String(CFG.plcIp || "")) problems.push(`plc_ip=${s.plc_ip}`);
  if (Number(s.protocol_version || 0) !== WORKER_PROTOCOL_VERSION) problems.push(`protocol_version=${s.protocol_version}`);
  if (String(s.worker_body_sha256 || "") !== WORKER_BODY_SHA256) problems.push(`worker_body_sha256=${s.worker_body_sha256}`);
  if (!s.instance_id) problems.push("instance_id missing");
  if (problems.length) throw new Error(`live CODESYS worker fingerprint mismatch; controlled restart required: ${problems.join(", ")}`);
  return s;
}

// 进程无关的判活: 共享 worker 由任一进程拉起, 故只看 status(ready)+其 pid 是否存活, 不看本进程 workerChild
async function workerAlive() {
  const s = await readLiveStatus();
  return !!s && s.state === "ready";
}

// spawn 失败冷却: worker 报 error(典型=工程被人工 InoProShop 占用)后, 冷却期内不再拉起 EXE。
// 无冷却时上层(agent)每次重试都弹一个 GUI 窗口再失败(弹窗风暴); 与 codesys_ipc.py 同值。
const SPAWN_ERROR_COOLDOWN_MS = 60000;

async function assertNoFreshSpawnError() {
  const s = await readStatus();
  if (s && s.state === "error") {
    const ageMs = Date.now() - (s.ts || 0) * 1000;   // worker 写的 ts 单位为秒
    if (ageMs >= 0 && ageMs < SPAWN_ERROR_COOLDOWN_MS) {
      const left = Math.ceil((SPAWN_ERROR_COOLDOWN_MS - ageMs) / 1000);
      throw new Error(
        `InoProShop 启动冷却中(${Math.round(ageMs / 1000)}s 前打开工程失败, 剩余 ${left}s): ${s.error || ""}\n` +
        "工程可能正被人工打开的 InoProShop 占用; 请在该窗口关闭工程(文件→关闭工程)后重试, 不要反复重试本工具");
    }
  }
}

// 跨进程冷启动互斥: O_EXCL 原子创建 spawn.lock. 返回 true=胜者(去 spawn), false=败者(去等就绪).
// 仅持有者已死时回收；活 PID 永不按年龄夺锁，owner token 防旧 owner 误删下一任锁。
async function acquireSpawnLock() {
  const ownerToken = crypto.randomBytes(16).toString("hex");
  const payload = JSON.stringify({ pid: process.pid, ts: Date.now() / 1000, owner_token: ownerToken });
  for (;;) {
    try {
      const fh = await fs.open(SPAWN_LOCK_PATH, "wx");  // wx = O_CREAT|O_EXCL, 已存在则抛 EEXIST
      try { await fh.writeFile(payload, "utf8"); } finally { await fh.close(); }
      spawnLockToken = ownerToken;
      return true;
    } catch (e) {
      if (e.code !== "EEXIST") throw e;
      let held = null;
      try { held = JSON.parse(await fs.readFile(SPAWN_LOCK_PATH, "utf8")); } catch {}
      const stale = !!held && !pidAlive(held.pid);
      if (stale && await removeLockIfOwned(SPAWN_LOCK_PATH, held.owner_token)) continue;
      return false;
    }
  }
}

async function releaseSpawnLock() {
  await removeLockIfOwned(SPAWN_LOCK_PATH, spawnLockToken);
  spawnLockToken = null;
}

// 胜者: 拉起 InoProShop 并等 worker 就绪(首次冷启动较慢)
async function spawnWorker() {
  await fs.mkdir(REQ_DIR, { recursive: true });
  await fs.mkdir(RESP_DIR, { recursive: true });
  await safeUnlink(STATUS_PATH);
  await safeUnlink(STOP_PATH);
  await buildWorkerScript();

  log(`启动 InoProShop(带 UI) 常驻 worker: ${CFG.exe}`);
  // 关键: 不能加 --noUI(SP11 下 projects.open 会 NPE); argv 直传避免 shell 引号问题
  workerChild = spawn(CFG.exe, [`--profile=${CFG.profile}`, `--runscript=${WORKER_SCRIPT}`], {
    detached: false,
    stdio: "ignore",
    windowsHide: false,
  });
  workerChild.on("exit", (code) => { log(`InoProShop worker 退出 code=${code}`); workerChild = null; });

  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    const s = await readStatus();
    if (s && s.state === "ready") {
      await readLiveStatus();  // fingerprint must match before this client attaches
      log("worker ready");
      return;
    }
    if (s && s.state === "error") throw new Error("worker 打开工程失败: " + (s.error || "") + "\n" + (s.trace || ""));
    if (!workerChild) throw new Error("InoProShop 进程提前退出, 未能就绪");
    await sleep(500);
  }
  throw new Error("等待 worker 就绪超时(150s)");
}

// 败者: 等胜者把共享 worker 拉起就绪后 attach; error 仅在 spawn 锁已释放(胜者收尾)时才认定真失败
async function waitReady() {
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    if (await workerAlive()) { log("attach 到已就绪的共享 worker"); return; }
    const s = await readStatus();
    if (s && s.state === "error") {
      let lockGone = false;
      try { await fs.access(SPAWN_LOCK_PATH); } catch { lockGone = true; }
      if (lockGone) throw new Error("worker 打开工程失败: " + (s.error || "") + "\n" + (s.trace || ""));
    }
    await sleep(500);
  }
  throw new Error("等待共享 worker 就绪超时(150s)");
}

async function startWorker() {
  // 胜者 spawn, 败者等就绪; 胜者收尾删 spawn.lock 放行败者
  const won = await acquireSpawnLock();
  if (won) {
    try { await spawnWorker(); }
    finally { await releaseSpawnLock(); }
  } else {
    await waitReady();
  }
}

async function ensureWorker() {
  if (await workerAlive()) return;
  await assertDeployGuardAllows("start_worker");
  await assertNoFreshSpawnError();   // 占用冷却: 冷却期内快速失败, 不弹新窗口
  if (!startLock) {
    startLock = startWorker().finally(() => { startLock = null; });
  }
  await startLock;
}

// 观测型停止: 读共享 status 的活体 pid, 写哨兵后轮询其消亡 — 与 codesys_ipc.py
// _stop_worker_blocking 同语义。attach 模式(workerChild=null, idle=0 常驻拓扑的常态)下
// 旧实现只等自己的子进程句柄 → 假成功。注意用 readLiveStatus 而非 ready-only 的
// workerAlive: opening/error 活体同样可停。默认 30s 与 codesys_ipc.py stop_worker 同值。
// 返回: true=worker 已停(pid 消亡, .project 文件锁已释放);
//       false=无活体可停(不写哨兵), 或超时未停(哨兵已回收=取消停止, 与 Python 侧对称;
//       调用方读 readLiveStatus 区分两种 false)。
async function stopWorker(timeoutMs = 30000) {
  await assertDeployGuardAllows("shutdown");
  const s = await readLiveStatus();
  if (!s) return false;                     // 无活体: 不写哨兵(残留哨兵会毒杀下一个 worker)
  const pid = s.pid;
  try { await writeJsonAtomic(STOP_PATH, { requested_at: Date.now() / 1000, owner_pid: process.pid }); } catch {}
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!pidAlive(pid)) return true;        // 等进程真正退出: 文件锁随进程消亡才释放
    await sleep(200);
  }
  // Never hard-kill InoProShop here: another client may have an in-flight physical
  // download whose outcome would become unknowable.  Timeout means cancellation.
  await safeUnlink(STOP_PATH);              // 超时=取消停止: 回收哨兵, 防 worker 结束长操作后被延迟毒杀
  return false;
}

// ---------- 单写者租约 ----------
// 独占 op(改内存/落盘/编译/部署)需抢 write.lock; 共享 op(读/列举/状态)不抢锁 -> 写入期间读仍可并发
const EXCLUSIVE_OPS = new Set(["write", "create", "save", "compile", "generate_code", "deploy"]);

async function acquireWriteLock(timeoutMs) {
  const ownerToken = crypto.randomBytes(16).toString("hex");
  const payload = JSON.stringify({ owner_pid: process.pid, ts: Date.now() / 1000, owner_token: ownerToken });
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      const fh = await fs.open(WRITE_LOCK_PATH, "wx");
      try { await fh.writeFile(payload, "utf8"); } finally { await fh.close(); }
      return ownerToken;
    } catch (e) {
      if (e.code !== "EEXIST") throw e;
      let held = null;
      try { held = JSON.parse(await fs.readFile(WRITE_LOCK_PATH, "utf8")); } catch {}
      const stale = !!held && !pidAlive(held.owner_pid);
      if (stale && await removeLockIfOwned(WRITE_LOCK_PATH, held.owner_token)) continue;
      if (Date.now() > deadline) throw new Error(`另一个客户端正在写入(owner=${held.owner_pid}); 写锁等待超时`);
      await sleep(150);
    }
  }
}
async function releaseWriteLock(ownerToken) {
  await removeLockIfOwned(WRITE_LOCK_PATH, ownerToken);
}

// ---------- 会话属主租约(session.owner): 可抢占的会话级独占 ----------
// 与人工接管(manual_control)正交: 那是"人类属主挡所有自动方"; 这里是"某个自动方临时独占
// 共享实例, 挡其它自动方的写类 op"。两种持有姿势共用同一份 session.owner:
//   - 自动持有(默认): 每个写类 op 经 call() -> claimOrWait 原子盖章 + 刷新 last_activity; 裸调用即持有,
//     最后一次 op 后 IDLE_RELEASE 秒空闲即可被抢占。agent 无需懂 session。
//   - 显式持有(codesys_session_acquire): 抢占后启 setInterval 刷新器每 T/2 刷 last_activity, 免于空闲
//     抢占, 直到显式 release / 本进程退出(pid 死) / 超 MAX_HOLD。供 agent 长事务。
// 抢占判定与原子夺锁沿用 write.lock 的 pidAlive + owner_token 陈旧回收范式(与 codesys_ipc.py 同语义镜像)。
const OWNER_ID = `${os.hostname()}:${process.pid}:${crypto.randomBytes(4).toString("hex")}`;
let sessionLabel = A.label || "mcp";
let sessionToken = null;
let sessionAcquiredAt = null;
let sessionRefresher = null;   // setInterval 句柄(显式持有期间保活)

async function readOwner() { try { return await readJson(SESSION_OWNER_PATH); } catch { return null; } }

// 属主是否"被存活属主实际持有中"(= 不可被抢占): 记录存在 且 pid 存活 且 未空闲超阈 且 未超 MAX_HOLD
function ownerIsHeld(owner) {
  if (!owner) return false;
  if (!pidAlive(owner.pid)) return false;
  const now = Date.now() / 1000;
  if (now - Number(owner.last_activity || 0) > CFG.sessionIdleReleaseSec) return false;
  if (now - Number(owner.acquired_at || 0) > CFG.sessionMaxHoldSec) return false;
  return true;
}

// 构造新租约内容 + 其 owner_token(每次盖章换新 token, 使空闲抢占无 TOCTOU); acquired_at 首盖保持
function newOwnerPayload() {
  const now = Date.now() / 1000;
  if (sessionAcquiredAt === null) sessionAcquiredAt = now;
  const token = crypto.randomBytes(16).toString("hex");
  return {
    payload: {
      owner_id: OWNER_ID, label: sessionLabel, pid: process.pid,
      acquired_at: sessionAcquiredAt, last_activity: now, owner_token: token,
    },
    token,
  };
}

async function refreshOwner() {
  const held = await readOwner();
  if (!held || held.owner_id !== OWNER_ID) return;   // 已被抢占: 静默停止刷新
  const { payload, token } = newOwnerPayload();
  await writeJsonAtomic(SESSION_OWNER_PATH, payload);
  sessionToken = token;
}

async function releaseOwner() {
  const token = sessionToken;
  sessionToken = null;
  sessionAcquiredAt = null;
  if (token) await removeLockIfOwned(SESSION_OWNER_PATH, token);
}

// 写类 op 的会话属主门: 抢占/盖章 session.owner; 被存活外部属主独占则阻塞轮询至超时抛忙
async function claimOrWait(op, waitTimeoutMs) {
  // 本门跑在 ensureWorker 之前(见 call), 首次调用时 ipc 目录可能尚未由 spawn 创建
  await fs.mkdir(CFG.ipcDir, { recursive: true });
  const deadline = Date.now() + waitTimeoutMs;
  for (;;) {
    let fh = null;
    try {
      fh = await fs.open(SESSION_OWNER_PATH, "wx");   // wx = O_CREAT|O_EXCL
    } catch (e) {
      if (e.code !== "EEXIST") throw e;
      const held = await readOwner();
      if (held && held.owner_id === OWNER_ID) { await refreshOwner(); return; }
      if (!ownerIsHeld(held)) {
        // 可抢占: 按文件里记录的 owner_token 删旧租约再重试; 属主刚 restamp 换 token 则删除失败 → 重评
        const staleToken = held && held.owner_token;
        if (staleToken && await removeLockIfOwned(SESSION_OWNER_PATH, staleToken)) continue;
        if (Date.now() > deadline) throw new Error(`无法抢占 PLC 会话属主(陈旧租约无有效 token 或刚被刷新); 等待 ${waitTimeoutMs}ms 超时`);
        await sleep(150); continue;
      }
      if (Date.now() > deadline) throw new Error(`PLC 实例正被 ${held ? held.label : "?"} 会话独占(op=${op}); 等待 ${waitTimeoutMs}ms 超时`);
      await sleep(150); continue;
    }
    // wx 夺得空闲: 写入本客户端租约(全新 acquired_at)
    try {
      sessionAcquiredAt = null;
      const { payload, token } = newOwnerPayload();
      await fh.writeFile(JSON.stringify(payload), "utf8");
      sessionToken = token;
    } finally { await fh.close(); }
    return;
  }
}

function startSessionRefresher() {
  if (sessionRefresher) return;
  const intervalMs = Math.max(50, (CFG.sessionIdleReleaseSec / 2) * 1000);   // 严格 < IDLE_RELEASE
  sessionRefresher = setInterval(() => { refreshOwner().catch(() => {}); }, intervalMs);
  if (sessionRefresher.unref) sessionRefresher.unref();   // 不阻止进程随 transport 关闭退出
}
function stopSessionRefresher() {
  if (sessionRefresher) { clearInterval(sessionRefresher); sessionRefresher = null; }
}

async function acquireSession(label, waitMs) {
  if (label) sessionLabel = String(label);
  await claimOrWait("acquire", waitMs || CFG.sessionWaitTimeoutSec * 1000);
  startSessionRefresher();
}
async function releaseSession() {
  stopSessionRefresher();
  await releaseOwner();
}

// 读式属主快照(供 codesys_status 合并; 不启动 IDE, 全本地读)
async function sessionOwnerSnapshot() {
  const owner = (await readOwner()) || {};
  const ownerAlive = owner.pid ? pidAlive(owner.pid) : false;
  const idle = owner.last_activity ? Math.round((Date.now() / 1000 - Number(owner.last_activity)) * 1000) / 1000 : null;
  return { owner, owned: ownerIsHeld(owner), owner_alive: ownerAlive, owner_idle_sec: idle, owner_self: OWNER_ID };
}

// ---------- 文件 IPC 调用 ----------
async function call(op, args, timeoutMs) {
  await assertNotManualControl(op);
  await assertDeployGuardAllows(op);
  const exclusive = EXCLUSIVE_OPS.has(op);
  if (exclusive) {
    // 会话属主门: 写类 op 抢占/盖章 session.owner(裸调用即自动持有); 被存活外部属主独占则
    // 阻塞轮询至 WAIT_TIMEOUT 超时抛忙。显式持有(codesys_session_acquire)时命中"属我"只刷新。
    await claimOrWait(op, CFG.sessionWaitTimeoutSec * 1000);
  }
  await ensureWorker();
  const leased = op !== "status";
  let writeLockToken = null;
  let reqPath = null;
  if (leased) await beginLease(op);
  try {
    if (exclusive) {
      writeLockToken = await acquireWriteLock(timeoutMs || 60000);
      await assertDeployGuardAllows(op);  // under-lock recheck closes guard-creation race
    }
    const id = crypto.randomBytes(8).toString("hex");
    reqPath = path.join(REQ_DIR, id + ".req.json");
    const tmpPath = reqPath + ".tmp";
    await fs.writeFile(tmpPath, JSON.stringify({
      op, args: args || {}, client_pid: process.pid, issued_at: Date.now() / 1000,
    }), "utf8");
    await fs.rename(tmpPath, reqPath);

    const respPath = path.join(RESP_DIR, id + ".resp.json");
    const deadline = Date.now() + (timeoutMs || 60000);
    while (Date.now() < deadline) {
      try {
        const resp = await readJson(respPath);
        await safeUnlink(respPath);
        await safeUnlink(reqPath);
        if (!resp.ok) throw new Error(resp.error + (resp.trace ? "\n" + resp.trace : ""));
        return resp.result;
      } catch (e) {
        if (e instanceof SyntaxError || (e && e.code === "ENOENT")) { await sleep(80); continue; }
        throw e;
      }
    }
    await safeUnlink(reqPath);  // best-effort revoke if worker has not atomically claimed it
    throw new Error(`操作 '${op}' 超时(${timeoutMs || 60000}ms); worker 可能在编译或无响应`);
  } finally {
    if (reqPath) await safeUnlink(reqPath);
    if (exclusive) await releaseWriteLock(writeLockToken);
    if (leased) await endLease(op);
  }
}

const ok = (obj) => ({ content: [{ type: "text", text: typeof obj === "string" ? obj : JSON.stringify(obj, null, 2) }] });
const fail = (msg) => ({ content: [{ type: "text", text: String(msg) }], isError: true });

// ---------- MCP server ----------
const server = new McpServer({ name: "inoproshop-codesys", version: "0.1.0" });

server.tool("codesys_status", "查询常驻 worker / 工程状态 + 会话属主(session)信息(并在需要时懒启动 InoProShop)", {}, async () => {
  try {
    const st = await call("status", {}, 160000);
    // 附带本地读到的会话属主快照(谁在独占实例、空闲多久), 不额外启动 IDE
    return ok({ ...st, session: await sessionOwnerSnapshot() });
  } catch (e) { return fail(e.message); }
});

server.tool("codesys_list_pous", "列出工程 Application 下可编辑的 POU(返回路径如 Application/收集流程)", {
  textual_only: z.boolean().optional().describe("仅含 ST 声明/实现的对象, 默认 true"),
}, async (a) => {
  try { return ok(await call("list", { textual_only: a.textual_only !== false }, 120000)); } catch (e) { return fail(e.message); }
});

server.tool("codesys_read_pou", "读取某 POU 的声明(VAR)与实现(ST)文本", {
  path: z.string().describe("POU 路径, 如 Application/Expand_process_展开流程"),
}, async (a) => {
  try {
    const r = await call("read", { path: a.path }, 60000);
    return ok(`# ${r.path}  (has_decl=${r.has_decl}, has_impl=${r.has_impl})\n\n===== DECLARATION =====\n${r.declaration}\n\n===== IMPLEMENTATION =====\n${r.implementation}`);
  } catch (e) { return fail(e.message); }
});

server.tool("codesys_write_pou", "写入某 POU 的声明/实现(整体替换; save=true 时落盘到 .project)", {
  path: z.string().describe("POU 路径"),
  declaration: z.string().optional().describe("新的声明(VAR 块)文本; 省略则不动"),
  implementation: z.string().optional().describe("新的实现(ST 主体)文本; 省略则不动"),
  save: z.boolean().optional().describe("是否立即保存工程, 默认 false"),
}, async (a) => {
  try {
    return ok(await call("write", {
      path: a.path,
      declaration: a.declaration === undefined ? null : a.declaration,
      implementation: a.implementation === undefined ? null : a.implementation,
      save: a.save === true,
    }, 60000));
  } catch (e) { return fail(e.message); }
});

server.tool("codesys_caps", "列出某对象暴露的 ScriptEngine 成员名(只读探针; 用于确认 create_action/create_pou 在本机分支上可用)", {
  path: z.string().describe("对象路径, 如 Application/50_action/FeedLift_L2"),
}, async (a) => {
  try { return ok(await call("caps", { path: a.path }, 60000)); } catch (e) { return fail(e.message); }
});

server.tool("codesys_create_object", "在已有 POU 下新建 Action(或在 Application 下新建 POU); 正文为空, 随后用 codesys_write_pou 填 ST。同名已存在则原样返回(幂等)", {
  parent: z.string().describe("父对象路径, 如 Application/50_action/FeedLift_L2"),
  name: z.string().describe("新对象名, 如 A13_feed_clear"),
  kind: z.enum(["action", "pou"]).optional().describe("action(默认) 或 pou"),
  language: z.string().optional().describe("显式实现语言; 省略即继承父对象语言(通常 ST)"),
  save: z.boolean().optional().describe("是否立即保存工程, 默认 false"),
}, async (a) => {
  try {
    return ok(await call("create", {
      parent: a.parent, name: a.name, kind: a.kind || "action",
      language: a.language === undefined ? null : a.language,
      save: a.save === true,
    }, 60000));
  } catch (e) { return fail(e.message); }
});

server.tool("codesys_compile", "编译(build)Application, 返回错误/警告列表(来自编译消息类别)", {}, async () => {
  try { return ok(await call("compile", {}, 240000)); } catch (e) { return fail(e.message); }
});

server.tool("codesys_generate_code", "离线生成活动 Application 的 Symbol Configuration XML；不登录、不下载 PLC", {}, async () => {
  try { return ok(await call("generate_code", {}, 240000)); } catch (e) { return fail(e.message); }
});

server.tool("codesys_save", "保存工程(.project 落盘)", {}, async () => {
  try { return ok(await call("save", {}, 60000)); } catch (e) { return fail(e.message); }
});

server.tool("codesys_shutdown", "停止常驻 worker 并关闭 InoProShop", {}, async () => {
  try {
    await assertNotManualControl("shutdown");
    const stopped = await stopWorker(30000);
    if (stopped) return ok("worker 已停止, InoProShop 已关闭");
    const s = await readLiveStatus();
    if (s) return fail("等待 worker 停止超时(30s); InoProShop 可能在长操作或弹了对话框(停止已取消, 哨兵已回收)");
    return ok("worker 本就不在线, 无需停止");
  } catch (e) { return fail(e.message); }
});

server.tool(
  "codesys_session_acquire",
  "显式抢占并独占共享 InoProShop 一段会话。普通改动无需它——写类工具(write/compile/save/generate_code)会自动持有实例, 最后一次操作后约 60s 空闲才被别的进程接管。仅当你要连续做一长串改动、且中间夹着大段思考或等待(可能超过空闲阈值)时才显式 acquire, 把实例钉住不被抢; 做完务必调用 codesys_session_release。被别的进程独占时会阻塞等待至超时。",
  {
    label: z.string().optional().describe("本次持有的展示标签, 如 'agent:重构泵控'"),
    wait_ms: z.number().optional().describe("被别的进程独占时最长等待毫秒, 默认 300000; 超时抛忙"),
  },
  async (a) => {
    try {
      await acquireSession(a.label, a.wait_ms);
      const snap = await sessionOwnerSnapshot();
      return ok({ acquired: true, ...snap });
    } catch (e) { return fail(e.message); }
  },
);

server.tool(
  "codesys_session_release",
  "释放 codesys_session_acquire 取得的会话独占, 让其它进程(后端 / 别的 agent)可立即接管共享实例。",
  {},
  async () => {
    try { await releaseSession(); return ok("已释放会话属主"); } catch (e) { return fail(e.message); }
  },
);

// ---------- 生命周期 ----------
// worker 是被多客户端共享的守护进程: 本 server 断开/退出不停它(避免误杀正被其它 agent 使用的实例),
// 残留由 worker 自身空闲超时(IDLE_TIMEOUT_SEC)收尾关闭; 仅 codesys_shutdown 工具显式 stopWorker。
process.on("SIGTERM", () => process.exit(0));
process.on("SIGINT", () => process.exit(0));

// ---------- 进程内自测 (--selftest): MCP transport 启动前拦截, 跑完即退 ----------
// 验收: node eit_ptlc/tools/codesys-mcp/server.mjs --selftest (退出码 0 = 全 PASS)。
// A 包搭骨架(锁秒制 F5 ①② + stopWorker 契约 F4 ③④), B 包在此追加用例。
async function runSelftest() {
  // 裸跑时重入自身并注入临时 IPC 目录: CFG 及各 *_PATH 常量在模块加载时已定型,
  // 只能经 CODESYS_IPC_DIR 环境变量(既有注入点)在子进程里改指, 避免污染真实 ipc/。
  if (!process.env.CODESYS_SELFTEST_REENTER) {
    const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "codesys-selftest-"));
    const r = spawnSync(process.execPath, [fileURLToPath(import.meta.url), "--selftest"], {
      stdio: "inherit",
      env: { ...process.env, CODESYS_IPC_DIR: tmp, CODESYS_SELFTEST_REENTER: "1" },
    });
    process.exit(r.status === null ? 1 : r.status);
  }
  const failures = [];
  const check = (name, cond, detail = "") => {
    if (cond) log(`PASS ${name}`);
    else { failures.push(name); log(`FAIL ${name}: ${detail}`); }
  };
  await fs.mkdir(CFG.ipcDir, { recursive: true });
  const nowSec = () => Math.floor(Date.now() / 1000);

  // ① F5: 秒级 ts + 存活 pid(本进程)的锁不被判 stale(毫秒判定曾恒把 Python 活锁当陈旧而抢)
  await writeJsonAtomic(SPAWN_LOCK_PATH, { pid: process.pid, ts: nowSec() });
  const won = await acquireSpawnLock();
  check("live_spawn_lock_not_stolen", won === false, `won=${won}`);
  await safeUnlink(SPAWN_LOCK_PATH);

  await writeJsonAtomic(WRITE_LOCK_PATH, { owner_pid: process.pid, ts: nowSec() });
  let writeWaited = false;
  try { await acquireWriteLock(400); }
  catch (e) { writeWaited = /写锁等待超时/.test(e.message); }
  check("live_write_lock_not_stolen", writeWaited, "acquireWriteLock 未在活锁上等待");
  await safeUnlink(WRITE_LOCK_PATH);

  // ② F5 对偶: 死 pid 锁仍被回收(pid 存活检查是既有回收路径, 秒化不得破坏它)
  const dead = spawnSync(process.execPath, ["-e", ""]);   // 立即退出的子进程 → 必死 pid
  await writeJsonAtomic(SPAWN_LOCK_PATH, { pid: dead.pid, ts: nowSec(), owner_token: "dead-spawn-owner" });
  const won2 = await acquireSpawnLock();
  check("dead_spawn_lock_reclaimed", won2 === true, `won=${won2}`);
  await releaseSpawnLock();

  await writeJsonAtomic(WRITE_LOCK_PATH, { owner_pid: dead.pid, ts: nowSec(), owner_token: "dead-write-owner" });
  let reclaimed = true;
  let reclaimedToken = null;
  try { reclaimedToken = await acquireWriteLock(2000); } catch (e) { reclaimed = false; }
  check("dead_write_lock_reclaimed", reclaimed, "死持有者的 write.lock 未被夺取");
  await releaseWriteLock(reclaimedToken);

  // ③ F4: 活体不消费哨兵(模拟深陷长操作) → stopWorker 超时返回 false 且哨兵被回收(与 Python F3 对称)
  const child = spawn(process.execPath, ["-e", "setTimeout(()=>{},30000)"], { stdio: "ignore" });
  await writeJsonAtomic(STATUS_PATH, {
    state: "ready", pid: child.pid, ts: nowSec(),
    project: canonicalProject(CFG.project), plc_ip: CFG.plcIp,
    instance_id: "selftest-worker", protocol_version: WORKER_PROTOCOL_VERSION,
    worker_body_sha256: WORKER_BODY_SHA256,
  });
  const stopped = await stopWorker(1500);
  let sentinelGone = false;
  try { await fs.access(STOP_PATH); } catch { sentinelGone = true; }
  check("stop_timeout_false_and_recycled", stopped === false && sentinelGone,
        `stopped=${stopped}, sentinelGone=${sentinelGone}`);
  try { child.kill(); } catch {}
  await safeUnlink(STATUS_PATH);

  // ④ F4: attach 模式无 status → 不写哨兵直接 false(假成功修复的对偶: 也不做假动作)
  const stopped2 = await stopWorker(1000);
  let sentinelAbsent = false;
  try { await fs.access(STOP_PATH); } catch { sentinelAbsent = true; }
  check("stop_no_status_false_no_sentinel", stopped2 === false && sentinelAbsent,
        `stopped=${stopped2}, sentinelAbsent=${sentinelAbsent}`);

  // F9: BOM session_control — readJson 剥 BOM 后接管门必须拦截 (split-brain 回归; 与
  // worker_body.read_json_file / codesys_ipc._read_json(utf-8-sig) 同语义镜像)
  await fs.writeFile(SESSION_CONTROL_PATH,
    "\ufeff" + JSON.stringify({ manual_control: true, owner: "selftest" }), "utf8");
  let bomBlocked = false;
  try { await assertNotManualControl("write"); } catch { bomBlocked = true; }
  check("bom_control_gate_blocks", bomBlocked, "BOM 接管标志被客户端门放行");
  await safeUnlink(SESSION_CONTROL_PATH);

  // F8: TTL 逃生阀 — 过期接管标志放行; 新鲜/旧格式(无 updated_at)仍拦截
  await writeJsonAtomic(SESSION_CONTROL_PATH,
    { manual_control: true, owner: "ghost", updated_at: Date.now() / 1000 - 25 * 3600 });
  let expiredPassed = true;
  try { await assertNotManualControl("write"); } catch { expiredPassed = false; }
  check("ttl_expired_manual_passes", expiredPassed, "过期标志仍被拦截");
  await writeJsonAtomic(SESSION_CONTROL_PATH,
    { manual_control: true, owner: "op", updated_at: Date.now() / 1000 });
  let freshBlocked = false;
  try { await assertNotManualControl("write"); } catch { freshBlocked = true; }
  check("ttl_fresh_manual_blocks", freshBlocked, "新鲜标志未被拦截");
  await writeJsonAtomic(SESSION_CONTROL_PATH, { manual_control: true, owner: "legacy" });
  let legacyBlocked = false;
  try { await assertNotManualControl("write"); } catch { legacyBlocked = true; }
  check("ttl_legacy_manual_blocks", legacyBlocked, "旧格式(无 updated_at)被误判过期");
  await safeUnlink(SESSION_CONTROL_PATH);

  // ⑤ 会话属主租约(session.owner): 空闲夺得 + 属我刷新(换 token) + release 清除
  await safeUnlink(SESSION_OWNER_PATH);
  await claimOrWait("write", 2000);
  const so1 = await readOwner();
  check("session_claim_free", !!so1 && so1.owner_id === OWNER_ID, `owner=${so1 && so1.owner_id}`);
  await claimOrWait("compile", 2000);
  const so2 = await readOwner();
  check("session_refresh_mine",
        !!so2 && so2.owner_id === OWNER_ID && so2.owner_token !== (so1 && so1.owner_token),
        "属我未刷新 token 或属主变了");
  await releaseOwner();
  let sessionGone = false;
  try { await fs.access(SESSION_OWNER_PATH); } catch { sessionGone = true; }
  check("session_release_clears", sessionGone, "release 后 session.owner 未清除");

  // ⑥ 死 pid 属主 → 立即抢占(崩溃兜底; 复用上面必死的 dead 子进程 pid)
  await writeJsonAtomic(SESSION_OWNER_PATH, {
    owner_id: "ghost", label: "ghost", pid: dead.pid,
    acquired_at: nowSec(), last_activity: nowSec(), owner_token: "dead-owner",
  });
  await claimOrWait("write", 2000);
  check("session_dead_owner_preempted", (await readOwner()).owner_id === OWNER_ID, "死属主未被抢占");
  await releaseOwner();

  // ⑦ 活外部属主(本进程 pid, 新鲜)→ 短等抛忙(会话级独占生效)
  await writeJsonAtomic(SESSION_OWNER_PATH, {
    owner_id: "other-live", label: "other", pid: process.pid,
    acquired_at: Date.now() / 1000, last_activity: Date.now() / 1000, owner_token: "live-owner",
  });
  let sessionBusy = false;
  try { await claimOrWait("write", 300); } catch (e) { sessionBusy = /会话独占|超时/.test(e.message); }
  check("session_live_owner_blocks", sessionBusy, "活外部属主未挡住");

  // ⑧ 空闲接管(last_activity 超 IDLE_RELEASE)→ 抢到
  await writeJsonAtomic(SESSION_OWNER_PATH, {
    owner_id: "idle-owner", label: "idle", pid: process.pid,
    acquired_at: nowSec(), last_activity: nowSec() - (CFG.sessionIdleReleaseSec + 5),
    owner_token: "idle-token",
  });
  await claimOrWait("write", 2000);
  check("session_idle_preempted", (await readOwner()).owner_id === OWNER_ID, "空闲属主未被接管");
  await releaseOwner();

  // ⑨ MAX_HOLD 逃生阀(acquired_at 超 MAX_HOLD, last_activity 新鲜)→ 抢到
  await writeJsonAtomic(SESSION_OWNER_PATH, {
    owner_id: "stuck-owner", label: "stuck", pid: process.pid,
    acquired_at: nowSec() - (CFG.sessionMaxHoldSec + 5), last_activity: Date.now() / 1000,
    owner_token: "stuck-token",
  });
  await claimOrWait("write", 2000);
  check("session_maxhold_preempted", (await readOwner()).owner_id === OWNER_ID, "超 MAX_HOLD 未被抢占");
  await releaseOwner();
  await safeUnlink(SESSION_OWNER_PATH);

  log(`selftest: 失败 ${failures.length}`);
  process.exit(failures.length ? 1 : 0);
}
if (process.argv.includes("--selftest")) {
  await runSelftest();   // 不返回: 内部 process.exit, 不会走到 MCP transport
}

const transport = new StdioServerTransport();
await server.connect(transport);
// Claude Code 关闭 server(stdin 结束/transport close)时本进程退出即可, 不动共享 worker
const prevOnClose = transport.onclose;
transport.onclose = () => { if (prevOnClose) try { prevOnClose(); } catch {} ; process.exit(0); };
process.stdin.on("end", () => process.exit(0));
log(`MCP server 就绪; exe=${CFG.exe} profile=${CFG.profile}\n  project=${CFG.project}\n  ipc=${CFG.ipcDir}`);
