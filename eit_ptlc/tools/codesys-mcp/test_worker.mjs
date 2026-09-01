// 直接文件 IPC 测 worker(不经 MCP / 无需 npm 依赖). 启动常驻 InoProShop worker,
// 依次发 status/list/read/compile 请求, 打印延迟与结果, 最后写 stop 关闭. 仅用 node 内置模块.
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const EXE = "D:\\InoProShop\\CODESYS\\Common\\InoProShop.exe";
const PROFILE = "InoProShop(V1.9.1.6)";
const PROJECT = "E:\\pTLC_platformUI\\eit_ptlc\\plc\\20260622.project";
const IPC = path.join(process.cwd(), "ipc_test");
const REQ = path.join(IPC, "requests"), RESP = path.join(IPC, "responses");
const STATUS = path.join(IPC, "worker.status"), STOP = path.join(IPC, "worker.stop");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function call(op, args, to = 120000) {
  const id = crypto.randomBytes(6).toString("hex");
  const rp = path.join(REQ, id + ".req.json");
  await fs.writeFile(rp + ".tmp", JSON.stringify({ op, args: args || {} }), "utf8");
  await fs.rename(rp + ".tmp", rp);
  const resp = path.join(RESP, id + ".resp.json");
  const dl = Date.now() + to;
  while (Date.now() < dl) {
    try { const r = JSON.parse(await fs.readFile(resp, "utf8")); await fs.unlink(resp); return r; }
    catch { await sleep(80); }
  }
  return { ok: false, error: "timeout" };
}

async function main() {
  await fs.mkdir(REQ, { recursive: true }); await fs.mkdir(RESP, { recursive: true });
  for (const f of [STATUS, STOP]) { try { await fs.unlink(f); } catch {} }
  const body = await fs.readFile("worker_body.py", "utf8");
  const header = `# -*- coding: utf-8 -*-\nIPC_DIR = r"${IPC}"\nPROJECT_PATH = r"${PROJECT}"\nPOLL_SEC = 0.12\nCOMPILE_CATEGORY = "97f48d64-a2a3-4856-b640-75c046e37ea9"\n\n`;
  const ws = path.join(IPC, "worker_active.py");
  await fs.writeFile(ws, header + body, "utf8");

  console.log("launching InoProShop worker...");
  const child = spawn(EXE, [`--profile=${PROFILE}`, `--runscript=${ws}`], { stdio: "ignore" });
  child.on("exit", (c) => console.log("worker process exit code=", c));

  let ready = false;
  for (let i = 0; i < 300; i++) {
    try { const s = JSON.parse(await fs.readFile(STATUS, "utf8"));
      if (s.state === "ready") { ready = true; break; }
      if (s.state === "error") { console.log("WORKER OPEN ERROR:", JSON.stringify(s)); child.kill(); return; }
    } catch {}
    await sleep(500);
  }
  console.log("worker ready =", ready);
  if (!ready) { console.log("未就绪, 检查 worker_active.py / InoProShop"); try { child.kill(); } catch {} return; }

  let t = Date.now();
  const st = await call("status"); console.log(`status (${Date.now() - t}ms):`, JSON.stringify(st));

  t = Date.now();
  const lst = await call("list", {}, 120000);
  console.log(`list (${Date.now() - t}ms): ok=${lst.ok} count=${lst.ok ? lst.result.count : "-"}`);
  if (lst.ok) console.log("  前 18 个 POU:\n   " + lst.result.pous.slice(0, 18).map((p) => p.path).join("\n   "));

  t = Date.now();
  const rd = await call("read", { path: "Application/Expand_process_展开流程" });
  console.log(`read (${Date.now() - t}ms): ok=${rd.ok}`, rd.ok ? `decl_len=${rd.result.declaration.length} impl_len=${rd.result.implementation.length}` : rd.error);

  t = Date.now();
  const cp = await call("compile", {}, 240000);
  console.log(`compile (${Date.now() - t}ms):`, rd.ok ? JSON.stringify(cp.ok ? { errors: cp.result.error_count, warnings: cp.result.warning_count, info: cp.result.info_count } : cp) : cp);

  // 第二次 status, 验证常驻热实例(应极快)
  t = Date.now();
  await call("status"); console.log(`status#2 (${Date.now() - t}ms) — 常驻热, 应亚秒`);

  console.log("发送 stop...");
  await fs.writeFile(STOP, "1", "utf8");
  await sleep(2500);
  console.log("done");
}
main().catch((e) => { console.error("harness err:", e); process.exit(1); });
