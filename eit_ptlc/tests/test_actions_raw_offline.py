"""动作 YAML 源文件读写 API 端到端离线测试 (HTTP)
=====================================================
功能:
    经 TestClient (sim) 验证「动作」编辑界面 YAML 源文件视图的后端闭环:
      - GET  /api/actions/{name}/raw  返回整文件原始文本 (含选中指令 + 同组其它指令)
      - PUT  改 label 后, GET /api/actions/{name} 反映新 label (写盘 + 热重载生效)
      - PUT  /api/actions/{name}/label 定点改显示名 (只动 label 行); DELETE /api/actions/{name}
             删除动作 (无引用可删 + 盘上移除; 被流程 call 引用 -> 400 拒绝且不写盘)
      - PUT  非法 YAML / 非法 kind / 跨文件重复动作名 -> 400, 且源文件原样不动 (绝不写坏文件)
      - POST /api/actions/reload  直接改盘上 YAML (绕开 API) 后触发磁盘重扫: 重载前 GET 仍旧值
             (证无自动热载), 重载后反映盘上新值; 盘上坏 YAML -> 400 且运行期不被污染
    测试写真实 config 文件, 结束在 finally 中原样还原, 不污染仓库。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_actions_raw_offline
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from eit_ptlc.runtime.bootstrap import create_sim_app

RAW_URL = "/api/actions/sampling.aspirate/raw"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48496/eit_ptlc/sim/")
    with TestClient(app) as client:  # 进入即触发 lifespan (装配 ActionsService 到 app.state.actions)
        # 抓取原始整文件文本 + 路径 (结束还原用)
        r0 = client.get(RAW_URL)
        check("get_raw_200", r0.status_code == 200, str(r0.status_code))
        body0 = r0.json()
        orig_text = body0["text"]
        orig_path = Path(body0["path"])
        check("raw_has_selected", "sampling.aspirate" in orig_text and "上样-吸取样品" in orig_text, orig_path.name)
        check("raw_has_siblings", "sampling.init" in orig_text and "sampling.spot" in orig_text,
              "整文件应含同组其它指令")
        check("raw_matches_disk", orig_text == orig_path.read_text(encoding="utf-8"), str(orig_path))

        # 找一个不同源文件 (group != 01_sampling) 的动作名, 供构造跨文件重复名
        acts = client.get("/api/actions").json()
        other_name = next((a["name"] for a in acts if a.get("group") != "01_sampling"), None)
        check("found_other_file_action", other_name is not None, "需要至少一个非 01_sampling 动作")

        try:
            # --- 负例 1: 非法 YAML 语法 -> 400, 源文件不动 ---
            sc = client.put(RAW_URL, json={"text": "a: {b: c\n"}).status_code  # 未闭合 flow mapping
            check("put_bad_yaml_400", sc == 400, f"status={sc}")
            check("bad_yaml_no_write", orig_path.read_text(encoding="utf-8") == orig_text, "坏 YAML 不得写盘")

            # --- 负例 2: 非法 kind (整文件替换为单条非法定义) -> 400, 源文件不动 ---
            bad_kind = "sampling.aspirate: {kind: bogus, station: sampling, action_code: 50, label: x}\n"
            sc = client.put(RAW_URL, json={"text": bad_kind}).status_code
            check("put_bad_kind_400", sc == 400, f"status={sc}")
            check("bad_kind_no_write", orig_path.read_text(encoding="utf-8") == orig_text, "非法 kind 不得写盘")

            # --- 负例 3: 跨文件重复动作名 -> 400, 源文件不动 ---
            if other_name is not None:
                dup = orig_text + f"\n{other_name}: {{kind: plc_l2, station: dup, action_code: 999, label: dup}}\n"
                sc = client.put(RAW_URL, json={"text": dup}).status_code
                check("put_dup_name_400", sc == 400, f"status={sc}")
                check("dup_name_no_write", orig_path.read_text(encoding="utf-8") == orig_text, "重复名不得写盘")

            # --- 负例 4: 缺 text 字段 -> 400 ---
            sc = client.put(RAW_URL, json={}).status_code
            check("put_no_text_400", sc == 400, f"status={sc}")

            # --- 负例 5: 未知动作 -> 404 ---
            sc = client.get("/api/actions/nope.nope/raw").status_code
            check("get_unknown_404", sc == 404, f"status={sc}")

            # --- label 定点端点: PUT /label -> 200 且 GET/raw 反映; 空 label -> 400; 未知 -> 404 ---
            ep_label = "上样-吸取样品_端点测试"
            rl = client.put("/api/actions/sampling.aspirate/label", json={"label": ep_label})
            check("label_put_200", rl.status_code == 200, rl.text)
            check("label_put_dto", rl.json().get("label") == ep_label, str(rl.json().get("label")))
            got = client.get("/api/actions/sampling.aspirate").json()["label"]
            check("label_get_reflects", got == ep_label, str(got))
            raw_now = client.get(RAW_URL).json()["text"]
            check("label_raw_line", f'label: "{ep_label}"' in raw_now, "raw 应含带引号的新 label 行")
            check("label_raw_keeps_siblings", "sampling.spot" in raw_now and "desc: |-" in raw_now,
                  "定点改 label 不得动其它内容")
            sc = client.put("/api/actions/sampling.aspirate/label", json={"label": "   "}).status_code
            check("label_blank_400", sc == 400, f"status={sc}")
            sc = client.put("/api/actions/nope.nope/label", json={"label": "x"}).status_code
            check("label_unknown_404", sc == 404, f"status={sc}")

            # --- 删除端点: 无引用的临时动作可删; 被流程引用的拒绝; 未知 -> 404 ---
            tmp_action = (
                "\n\nsampling.zz_tmp_delete:\n"
                "  kind: plc_l2\n"
                "  station: sampling\n"
                "  action_code: 999\n"
                "  label: 删除端点测试\n"
                "  desc: |-\n"
                "    临时动作, 仅供离线测试删除端点使用。\n"
            )
            rput = client.put(RAW_URL, json={"text": orig_text + tmp_action})
            check("del_setup_200", rput.status_code == 200, rput.text)
            rdel = client.delete("/api/actions/sampling.zz_tmp_delete")
            check("del_tmp_200", rdel.status_code == 200, rdel.text)
            sc = client.get("/api/actions/sampling.zz_tmp_delete").status_code
            check("del_tmp_gone", sc == 404, f"status={sc}")
            check("del_tmp_disk_gone", "zz_tmp_delete" not in orig_path.read_text(encoding="utf-8"),
                  "删除后盘上不应再有临时动作")
            rref = client.delete("/api/actions/sampling.init")
            check("del_referenced_400", rref.status_code == 400, f"status={rref.status_code}")
            check("del_referenced_detail", "引用" in str(rref.json().get("detail", "")), rref.text)
            check("del_referenced_no_write", "sampling.init:" in orig_path.read_text(encoding="utf-8"),
                  "被拒删除不得写盘")
            sc = client.delete("/api/actions/nope.nope").status_code
            check("del_unknown_404", sc == 404, f"status={sc}")

            # --- 正例: 改 label -> 200 -> 写盘 + 热重载, GET 单动作反映新 label ---
            new_label = "上样-吸取样品_测试"
            mod_text = orig_text.replace("label: 上样-吸取样品", f"label: {new_label}")
            check("label_substituted", mod_text != orig_text, "未替换到 label, 检查源文件 label 文案")
            rput = client.put(RAW_URL, json={"text": mod_text})
            check("put_valid_200", rput.status_code == 200, rput.text)
            adef = client.get("/api/actions/sampling.aspirate").json()
            check("hot_reload_label", adef["label"] == new_label, str(adef.get("label")))
            check("raw_reflects_change", client.get(RAW_URL).json()["text"] == mod_text, "GET raw 应回显新文本")

            # --- reload 正例: 直接写盘改 label (绕开 API) -> reload 前 GET 仍旧值 -> reload 后反映盘上新值 ---
            disk_label = "上样-吸取样品_盘改"
            disk_text = orig_text.replace("label: 上样-吸取样品", f"label: {disk_label}")
            check("reload_label_substituted", disk_text != orig_text, "未替换到 label")
            orig_path.write_text(disk_text, encoding="utf-8")     # 磁盘直改, 不经服务 (模拟手改 YAML)
            pre = client.get("/api/actions/sampling.aspirate").json()["label"]
            check("reload_no_autoload", pre != disk_label, f"未 reload 前不应看到盘上新 label: {pre}")
            rr = client.post("/api/actions/reload")
            check("reload_200", rr.status_code == 200, rr.text)
            check("reload_count_positive", rr.json().get("actions", 0) > 0, rr.text)
            post = client.get("/api/actions/sampling.aspirate").json()["label"]
            check("reload_picks_disk", post == disk_label, f"reload 后应反映盘上新 label: {post}")

            # --- reload 负例: 盘上写坏 YAML -> 400, 运行期不被污染 (GET 仍服务上一次成功重载的 label) ---
            orig_path.write_text("a: {b: c\n", encoding="utf-8")  # 未闭合 flow mapping
            rbad = client.post("/api/actions/reload")
            check("reload_bad_yaml_400", rbad.status_code == 400, f"status={rbad.status_code}")
            still = client.get("/api/actions/sampling.aspirate").json()["label"]
            check("reload_bad_keeps_runtime", still == disk_label, f"坏 YAML reload 不得污染运行期: {still}")
        finally:
            # 还原真实源文件 (直接写盘; app 随 TestClient 退出销毁, 内存态无需复位)
            orig_path.write_text(orig_text, encoding="utf-8")

    print(f"\n动作 YAML 源文件读写测试: 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
