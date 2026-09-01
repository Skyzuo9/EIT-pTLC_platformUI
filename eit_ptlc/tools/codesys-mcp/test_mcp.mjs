// 端到端测 MCP server: 用 MCP SDK client 经 stdio 拉起 server.mjs(它再懒启动 InoProShop),
// 列工具并调用 status/list/read/(安全的内存写探针+还原)/compile/shutdown. 写操作 save=false, 绝不落盘.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const TARGET = "Application/Expand_process_展开流程";
const text = (r) => (r.content && r.content[0] && r.content[0].text) || "";

async function main() {
  const transport = new StdioClientTransport({ command: "node", args: ["server.mjs"], cwd: process.cwd() });
  const client = new Client({ name: "smoke", version: "0.0.1" }, { capabilities: {} });
  await client.connect(transport);

  const tools = await client.listTools();
  console.log("TOOLS:", tools.tools.map((t) => t.name).join(", "));

  const call = async (name, args) => {
    const t = Date.now();
    const r = await client.callTool({ name, arguments: args || {} });
    return { ms: Date.now() - t, err: !!r.isError, text: text(r) };
  };

  let r = await call("codesys_status");
  console.log(`\n[status ${r.ms}ms err=${r.err}] ${r.text}`);

  r = await call("codesys_list_pous", {});
  const list = JSON.parse(r.text);
  console.log(`\n[list ${r.ms}ms err=${r.err}] count=${list.count}`);

  r = await call("codesys_read_pou", { path: TARGET });
  console.log(`\n[read ${r.ms}ms err=${r.err}] head:\n${r.text.slice(0, 240)}`);
  // 提取 implementation 原文(read 文本里 ===== IMPLEMENTATION ===== 之后)
  const marker = "===== IMPLEMENTATION =====\n";
  const original = r.text.slice(r.text.indexOf(marker) + marker.length);

  // 安全写: 追加探针, save=false(仅内存)
  const probe = original + "\n(* _mcp_smoke_probe *)\n";
  r = await call("codesys_write_pou", { path: TARGET, implementation: probe, save: false });
  console.log(`\n[write probe ${r.ms}ms err=${r.err}] ${r.text}`);

  r = await call("codesys_read_pou", { path: TARGET });
  console.log(`[verify probe] present=${r.text.includes("_mcp_smoke_probe")}`);

  // 还原原文, save=false
  r = await call("codesys_write_pou", { path: TARGET, implementation: original, save: false });
  r = await call("codesys_read_pou", { path: TARGET });
  console.log(`[verify restore] probe_gone=${!r.text.includes("_mcp_smoke_probe")}`);

  r = await call("codesys_compile", {});
  console.log(`\n[compile ${r.ms}ms err=${r.err}] ${r.text.slice(0, 200)}`);

  r = await call("codesys_shutdown", {});
  console.log(`\n[shutdown ${r.ms}ms] ${r.text}`);

  await client.close();
  console.log("\nDONE");
  process.exit(0);
}
main().catch((e) => { console.error("CLIENT ERR:", e); process.exit(1); });
