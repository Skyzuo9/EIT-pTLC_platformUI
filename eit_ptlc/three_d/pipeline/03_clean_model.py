"""
功能: 模型清理/重组/赋材质的启动器. 负责把 YAML 配置合并成一份 JSON 作业单,
      然后以无界面方式调用 Blender 执行 blender_clean.py.

为什么分两层: Blender 自带 Python 没有 PyYAML, 把配置解析留在系统 Python 这一侧,
Blender 侧只吃 JSON, 从而不需要往 Blender 环境里装任何第三方包.

用法:
    python 03_clean_model.py                          # minimal 阶段(M0: 只删减+赋材质+合并)
    python 03_clean_model.py --stage full             # full 阶段(M1: 另按 rig_map 重组与装配)
    python 03_clean_model.py --stage raw              # raw 阶段(装配台: 全量零件, 仅换官方臂)
    python 03_clean_model.py --input X.glb --output Y.glb
    python 03_clean_model.py --decimate               # 额外启用减面规则

参数: 见 main() 中的 argparse 定义
返回值: 无(产出 GLB + 报告 JSON)
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
from collections import deque

import yaml

from common import ensure_dir, human_size, load_config, log, timed, write_report

BLENDER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_clean.py")


def load_yaml(path: str) -> dict:
    """
    功能: 读取一个 YAML 配置文件; 文件不存在时返回空字典.
    参数:
        path: YAML 路径
    返回值: dict
    """
    if not os.path.isfile(path):
        log(f"提示: 配置不存在, 跳过: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def run_blender(
    blender_exe: str, job_path: str, console_log: str | None = None, timeout: int = 10800
) -> None:
    """
    功能: 以无界面模式调用 Blender 执行清理脚本, 过滤透传关键输出.
    参数:
        blender_exe: blender.exe 绝对路径
        job_path: 作业单 JSON 路径
        console_log: 全量控制台输出的落盘路径(每次运行覆盖); None 则不落盘
        timeout: 超时秒数
    返回值: None
    异常: RuntimeError, Blender 失败时抛出, 消息携带首个 traceback
    """
    if not os.path.isfile(blender_exe):
        raise FileNotFoundError(f"未找到 Blender: {blender_exe}; 请检查 pipeline.yaml 的 paths.blender")

    command = [
        blender_exe,
        "--background",
        "--factory-startup",  # 忽略用户配置与插件, 保证不同机器上行为一致
        "--python",
        BLENDER_SCRIPT,
        "--",
        "--job",
        job_path,
    ]
    log(f"调用 Blender: {' '.join(command[:4])} …")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    # 踩过的坑: 失败信息曾只保留"Traceback 之后的最后 20 行" —— Blender C++ 侧的
    # 日志(如 DracoDecoder)是块缓冲, 会晚于 Python 的 stderr 刷进管道, 把 traceback
    # 挤出窗口, 上层只看到一串解码行. 因此双缓冲: 首个 traceback 一出现就定格保留,
    # 全程末尾另存若干行兜底, 并把全量输出 tee 到 console_log 供事后翻查.
    python_failed = False
    first_tb: list[str] = []
    tail: deque[str] = deque(maxlen=40)
    sink = open(console_log, "w", encoding="utf-8", errors="replace", buffering=1) if console_log else None
    try:
        for line in process.stdout:
            line = line.rstrip()
            if sink:
                sink.write(line + "\n")
            if line:
                tail.append(line)
            if "Traceback (most recent call last)" in line:
                python_failed = True
            if python_failed and line and len(first_tb) < 30:
                first_tb.append(line)
            # Blender 启动时会刷一堆无关信息, 只透传我们自己的日志与明确的错误
            if line.startswith("[blender") or "Error" in line or "Traceback" in line or "error:" in line:
                print(line, flush=True)
    finally:
        if sink:
            sink.close()

    code = process.wait(timeout=timeout)
    # Blender 的 --python 脚本抛异常时进程仍可能退出码 0 —— 只看退出码会把陈旧的
    # 既有 GLB 误当成功产物, 恰好掩盖几何/标定失败, 所以 python_failed 也算失败.
    if code != 0 or python_failed:
        detail = "\n".join(first_tb if first_tb else list(tail))
        where = f"; 完整日志: {console_log}" if console_log else ""
        raise RuntimeError(f"Blender 执行失败(退出码 {code}){where}\n{detail}")


def glb_node_names(path: str) -> list[str]:
    """
    功能: 只读 GLB 头部的 JSON 块, 取出全部节点名(不碰后面的二进制数据).

    参数:
        path: GLB 路径
    返回值: list[str], 去重后的节点名; 读不出来返回空表
    """
    try:
        with open(path, "rb") as handle:
            magic, _version, _length = struct.unpack("<III", handle.read(12))
            if magic != 0x46546C67:  # 'glTF'
                return []
            chunk_len, chunk_type = struct.unpack("<II", handle.read(8))
            if chunk_type != 0x4E4F534A:  # 'JSON'
                return []
            document = json.loads(handle.read(chunk_len).decode("utf-8"))
    except (OSError, ValueError, struct.error):
        return []
    return sorted({n["name"] for n in document.get("nodes", []) if n.get("name")})


def source_stamp(text: str) -> str:
    """
    功能: 给一段源文本算一个"变没变"的戳(UTF-8 字节数 + FNV-1a 32 位).

    为什么不用 SHA-256: 装配台常从局域网 IP 走 http 打开, 那不是安全上下文,
    浏览器里 crypto.subtle 直接是 undefined —— 用它等于让告警条永久挂着.
    FNV-1a 两边各六行就能算, 而 TextEncoder 到处都有. 这里只判"文件变没变",
    不防篡改, 32 位再加长度前缀足够.

    参数:
        text: 源文件文本(行尾须已归一为 \\n, 与后端 read_text 给浏览器的一致)
    返回值: str, 形如 "8371:1a2b3c4d"
    """
    data = text.encode("utf-8")
    digest = 0x811C9DC5
    for byte in data:
        digest = ((digest ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{len(data)}:{digest:08x}"


def build_name_aliases(path: str, slugify) -> dict[str, str]:
    """
    功能: 为模型里的中文节点名算出拼音 slug 别名表.

    SolidWorks 原生导出的 GLB 保留了中文实例名(如 `展缸注射泵总装-1`), 可读性远好过拼音;
    但 prune_list.yaml / rig_map.yaml 里积累的几十条规则都是按拼音写的.
    所以这里算一份"中文名 → 拼音"的对照表随作业单交给 Blender, 让匹配时两种写法都能命中 ——
    规则不用重写, 模型里的名字也不用退回拼音.

    转换必须在这一侧做: Blender 自带的 Python 没有 pypinyin.

    参数:
        path: 输入 GLB 路径
        slugify: 01 步的 slugify 函数(与命名管线保持同一实现, 免得两边漂移)
    返回值: dict[str, str], 仅含带中文的名字
    """
    aliases: dict[str, str] = {}
    for name in glb_node_names(path):
        if not any("一" <= ch <= "鿿" for ch in name):
            continue
        try:
            slug = slugify(name)
        except Exception:  # noqa: BLE001 - 个别名字转换失败不该中断整轮
            continue
        if slug and slug != name:
            aliases[name] = slug
    return aliases


def _resolve_restore_rules(config: dict, pipeline_dir: str) -> list:
    """
    功能: 取 pipeline.yaml 的 restore_geometry 规则, 把素材路径解析成绝对路径.

    配置里写的是相对 three_d 模块根目录的路径(如 exports/parts/xxx.glb), 因为作业单
    要交给另一个进程里的 Blender 执行, 相对路径在那边会相对错的工作目录.

    参数:
        config: pipeline.yaml 内容
        pipeline_dir: 本脚本所在目录, 用于回推 three_d 模块根
    返回值: list, 素材路径已绝对化的规则表
    """
    rules = config.get("restore_geometry") or []
    root = config.get("paths", {}).get("root") or os.path.dirname(pipeline_dir)
    resolved = []
    for rule in rules:
        item = dict(rule)
        asset = item.get("part_glb") or ""
        if asset and not os.path.isabs(asset):
            item["part_glb"] = os.path.abspath(os.path.join(root, asset))
        resolved.append(item)
    return resolved


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    config = load_config()
    work_dir = config["paths"]["work"]
    pipeline_dir = os.path.dirname(os.path.abspath(__file__))

    sys.path.insert(0, pipeline_dir)
    from importlib import import_module

    slugify = import_module("01_fix_step_names").slugify

    # 默认输入由 pipeline.yaml 的 model_source 决定 —— 这正是那个开关存在的意义.
    # 踩过的坑: 此处曾写死 legacy STEP 产物, 于是"不带 --input 的重跑"(vite 插件就是)
    # 全部静默退回旧模型: 少 3 个总成、无原生材质名、兜底数暴涨, 且不报任何错.
    if str(config.get("model_source", "step")).lower() == "native_glb":
        default_input = config["sources"]["native_glb"]
    else:
        # 回退路径: 与 01/02 保持一致的中间产物命名
        stem = slugify(os.path.splitext(os.path.basename(config["sources"]["legacy_full_step"]))[0])
        default_input = os.path.join(work_dir, f"{stem}_named.raw.glb")

    parser = argparse.ArgumentParser(description="Blender 模型清理与赋材质")
    parser.add_argument("--input", default=default_input)
    parser.add_argument("--output", default=os.path.join(work_dir, "machine.clean.glb"))
    parser.add_argument("--stage", default="minimal", choices=["minimal", "full", "raw"])
    parser.add_argument("--decimate", action="store_true", help="启用 prune_list 中的减面规则")
    parser.add_argument("--no-join", action="store_true", help="minimal 阶段不按材质合并")
    parser.add_argument("--blender", default=config["paths"]["blender"])
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        raise SystemExit(
            f"错误: 输入文件不存在: {args.input}\n请先运行 02_convert_step.py"
        )

    # raw 阶段(装配台仅换臂)的所有落盘文件一律用独立名字:
    #   * 报告/structure 不能覆盖 full 链的同名产物 —— gen_twin_manifest 读的就是它们,
    #     被 raw 的精简报告顶掉后, 下一次单独重生成契约会拿到残缺数据且不报错;
    #   * 作业单 _blender_job.json 有并行会话在写, raw 用自己的文件互不干扰.
    is_raw = args.stage == "raw"
    default_clean = os.path.join(work_dir, "machine.clean.glb")
    if is_raw and os.path.abspath(args.output) == os.path.abspath(default_clean):
        # 手工跑忘了 --output 时别去覆盖 minimal 的默认产物
        args.output = os.path.join(work_dir, "machine.raw.glb")

    ensure_dir(args.output)
    report_path = os.path.join(
        work_dir, "03_raw_swap.report.json" if is_raw else "03_clean_model.report.json"
    )

    rig_map = load_yaml(os.path.join(pipeline_dir, "rig_map.yaml"))
    robot_spec = rig_map.get("robot") or {}
    kinematics = robot_spec.get("kinematics") or {}
    if kinematics:
        for key in ("mesh_dir", "xacro"):
            value = kinematics.get(key)
            if value and not os.path.isabs(value):
                kinematics[key] = os.path.abspath(os.path.join(pipeline_dir, value))
        calibration_path = kinematics.get("calibration")
        if calibration_path:
            if not os.path.isabs(calibration_path):
                calibration_path = os.path.abspath(os.path.join(pipeline_dir, calibration_path))
            robot_spec["calibration_data"] = load_yaml(calibration_path)

    prune_path = os.path.join(pipeline_dir, "prune_list.yaml")
    prune_cfg = load_yaml(prune_path)

    job = {
        "stage": args.stage,
        "input": os.path.abspath(args.input),
        "output": os.path.abspath(args.output),
        "report": report_path,
        # full 阶段额外产出节点层级清单, 供 gen_twin_manifest.py 生成绑定契约
        "structure": None if is_raw else os.path.join(work_dir, "structure.json"),
        "decimate": args.decimate,
        "join_by_material": not args.no_join,
        # raw 阶段(装配台)必须全量零件, 不做任何删减
        "prune": {} if is_raw else prune_cfg,
        # materials 全阶段都带: raw 也整机赋管线材质(2026-08 起, 指认视图要看清
        # 零件长相), 官方 STL 另按 MAT_ROBOT_* 规则取色
        "materials": load_yaml(os.path.join(pipeline_dir, "materials.yaml")),
        "rig_map": rig_map,
        # 中文节点名 -> 拼音 slug; 让按拼音写的旧规则在原生 GLB 上继续生效
        "name_aliases": build_name_aliases(os.path.abspath(args.input), slugify),
        # 空节点补几何: 装配导出丢了几何的零件, 用单件 GLB 素材补回(见 pipeline.yaml
        # restore_geometry 的成因说明). 全阶段都做 —— 装配台与正式模型都不该缺件.
        "restore_geometry": _resolve_restore_rules(config, pipeline_dir),
    }

    if is_raw:
        # raw 一个零件都不删, 但要产出"哪些零件会被删"的基线交给装配台标红 —— 判定
        # 必须由管线出: 浏览器早先自己按正则/尺寸再算一遍, 与管线漂移出四类错判
        # (见 blender_clean.prune_verdict). 顺带把 region_delete 的面岛分离成独立节点,
        # 否则"只删线不删电机"那截线缆按节点粒度根本没法标红.
        #
        # 戳的是 prune_list.yaml **原文**, 规则改了而 raw 没重跑时页面才好告警.
        # 必须按文本读(通用换行把 CRLF 归一成 \n): 后端 read_text 给浏览器的也是归一后的,
        # 按字节读会因为行尾风格不同而永远对不上戳.
        with open(prune_path, "r", encoding="utf-8") as handle:
            source_text = handle.read()
        job["prune_preview"] = {
            "config": prune_cfg,
            "output": os.path.join(work_dir, "prune_preview.json"),
            "source_stamp": source_stamp(source_text),
        }

        # 装配台的臂烘焙 robot-main.home 实测姿态(= CAD 原摆放/演示动画首帧),
        # 而非笔直的官方零位. 数值取实测点位注册表, 取不到就退化为零位并提示.
        points_path = os.path.abspath(
            os.path.join(pipeline_dir, "..", "app", "public", "generated", "robot-points.json")
        )
        try:
            with open(points_path, "r", encoding="utf-8") as handle:
                registry = json.load(handle)
            if registry.get("kinematicsCommit") != kinematics.get("commit"):
                raise ValueError(
                    f"robot-points.json 提交 {registry.get('kinematicsCommit')} 与 rig_map 不一致"
                )
            home_joint = registry["points"]["robot-main.home"]["joint"]
            if not isinstance(home_joint, list) or len(home_joint) != 6:
                raise ValueError(f"robot-main.home.joint 不是六轴角: {home_joint}")
            job["bake_joints_deg"] = home_joint
            log(f"装配台姿态: robot-main.home {[round(v, 2) for v in home_joint]}")
        except (OSError, KeyError, TypeError, ValueError) as err:
            log(f"提示: 取不到 robot-main.home, 装配台臂保持零位: {err}")

    job_path = os.path.join(work_dir, "_blender_job_raw.json" if is_raw else "_blender_job.json")
    ensure_dir(job_path)
    with open(job_path, "w", encoding="utf-8") as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)

    log(f"输入: {args.input} ({human_size(os.path.getsize(args.input))})")
    log(f"阶段: {args.stage}; 减面: {args.decimate}; 按材质合并: {not args.no_join}")

    with timed(f"Blender 清理 ({args.stage})"):
        run_blender(
            args.blender,
            job_path,
            console_log=os.path.join(work_dir, f"03_{args.stage}.console.log"),
        )

    if not os.path.isfile(args.output):
        raise SystemExit(f"错误: Blender 未产出文件: {args.output}")

    # 把合并成员元数据派生成独立小文件并写入 models/: 材质台的
    # 成员反查/命中候选在生产构建(没有 dev 中间件可读 clean_report)也要可用.
    # minimal 的 join_by_material 不产 members, raw 不合并 —— 缺字段时自然跳过.
    if not is_raw:
        try:
            with open(report_path, "r", encoding="utf-8") as handle:
                member_blocks = (json.load(handle).get("join") or {}).get("members")
        except (OSError, ValueError):
            member_blocks = None
        if member_blocks:
            members_path = os.path.join(config["paths"]["models"], "merge-members.json")
            ensure_dir(members_path)
            with open(members_path, "w", encoding="utf-8") as handle:
                # 部署资产走紧凑序列化(浏览器直接 fetch); 排查细节看 report 原件
                json.dump(
                    {
                        "version": 1,
                        "coordinateSystem": "gltf-y-up",
                        "source": os.path.basename(report_path),
                        "blocks": member_blocks,
                    },
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            log(f"合并成员清单已派生: {members_path} ({len(member_blocks)} 块)")

    # Blender 侧已写过详细报告, 这里补一份启动器视角的摘要
    summary = {
        "input": args.input,
        "output": args.output,
        "output_size": human_size(os.path.getsize(args.output)),
        "stage": args.stage,
        "blender_report": report_path,
    }
    write_report(
        os.path.join(
            work_dir, "03_raw_swap.launcher.json" if is_raw else "03_clean_model.launcher.json"
        ),
        summary,
    )
    log(f"完成: {args.output} ({summary['output_size']})")


if __name__ == "__main__":
    main()
