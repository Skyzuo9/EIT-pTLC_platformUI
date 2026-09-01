"""
功能: 无界面 Blender 执行器. 负责定位 blender.exe、生成临时脚本、调用 Blender 并回收输出.

为什么用无界面(headless)方式而不是社区常见的 GUI 插件式 blender-mcp:
    - 插件式需要 Blender 以图形界面常驻并监听 socket, 一旦窗口被关掉或弹出模态对话框,
      整条自动化链就断了, 不适合无人值守的资产管线;
    - 无界面方式每次调用都是干净的一次性进程(--factory-startup 还会忽略用户配置与插件),
      在不同机器上行为完全一致, 出错也只影响当次调用;
    - 缺点是没有"常驻场景"的概念, 因此本模块用"输入文件 + 脚本 + 输出文件"的方式
      来串联多次操作, 由调用方负责传递中间产物路径.

参数: 见各函数签名
返回值: 见各函数说明
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile

# 常见安装位置; 也可用环境变量 BLENDER_EXE 覆盖
_SEARCH_GLOBS = (
    r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
    r"C:\Program Files (x86)\Blender Foundation\Blender *\blender.exe",
    r"D:\Program Files\Blender Foundation\Blender *\blender.exe",
)


def find_blender() -> str:
    """
    功能: 定位 blender.exe.
    参数: 无
    返回值: str, 可执行文件绝对路径
    异常: FileNotFoundError, 未找到时抛出
    """
    env_path = os.environ.get("BLENDER_EXE")
    if env_path and os.path.isfile(env_path):
        return env_path

    candidates: list[str] = []
    for pattern in _SEARCH_GLOBS:
        candidates.extend(glob.glob(pattern))
    if not candidates:
        raise FileNotFoundError(
            "未找到 blender.exe; 请安装 Blender 或设置环境变量 BLENDER_EXE"
        )
    # 版本号大的排前面, 优先使用最新版
    return sorted(candidates, reverse=True)[0]


def run_script(
    code: str,
    argv: list[str] | None = None,
    timeout: int = 3600,
    factory_startup: bool = True,
) -> dict:
    """
    功能: 在无界面 Blender 中执行一段 Python 代码.

    参数:
        code: 要执行的 Python 源码(在 Blender 的解释器里运行, 可直接 import bpy)
        argv: 传给脚本的额外参数, 脚本内通过 sys.argv 中 "--" 之后的部分读取
        timeout: 超时秒数
        factory_startup: 是否忽略用户配置与插件(建议 True, 保证可复现)
    返回值: dict, 含 ok / returncode / stdout / stderr / script_path
    """
    blender = find_blender()

    script_file = tempfile.NamedTemporaryFile(
        mode="w", suffix="_twin_mcp.py", delete=False, encoding="utf-8"
    )
    script_file.write(code)
    script_file.close()

    command = [blender, "--background"]
    if factory_startup:
        command.append("--factory-startup")
    command += ["--python", script_file.name]
    if argv:
        command.append("--")
        command.extend(argv)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "script_path": script_file.name,
            "blender": blender,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Blender 执行超时({timeout}s)",
            "script_path": script_file.name,
            "blender": blender,
        }
    finally:
        # 保留脚本文件便于排查失败原因; 成功时删掉避免临时目录堆积
        try:
            if os.path.isfile(script_file.name):
                os.unlink(script_file.name)
        except OSError:
            pass


def extract_json_result(stdout: str, marker: str = "@@TWIN_RESULT@@") -> dict | None:
    """
    功能: 从 Blender 的 stdout 中提取脚本回传的 JSON 结果.

    Blender 启动时会打印大量无关信息, 因此约定脚本把结果打印成
    "@@TWIN_RESULT@@<json>" 一行, 由本函数挑出来解析.

    参数:
        stdout: Blender 的标准输出
        marker: 结果行前缀
    返回值: dict | None, 解析出的结果; 未找到或解析失败时返回 None
    """
    for line in stdout.splitlines():
        if line.startswith(marker):
            try:
                return json.loads(line[len(marker):])
            except json.JSONDecodeError:
                return None
    return None


# ---------------------------------------------------------------------------
# 预置脚本模板
# ---------------------------------------------------------------------------

# 通用前置代码: 导入模型 + 结果回传辅助函数
PRELUDE = '''
import bpy, json, math, os, sys

def _args():
    """功能: 取 "--" 之后的命令行参数. 参数: 无. 返回值: list[str]"""
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []

def emit(payload):
    """功能: 把结果以约定格式回传给调用方. 参数: payload 可序列化对象. 返回值: None"""
    print("@@TWIN_RESULT@@" + json.dumps(payload, ensure_ascii=False), flush=True)

def load_model(path):
    """功能: 清空场景并导入模型(按扩展名选择导入器). 参数: path 模型路径. 返回值: None"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    elif ext in (".obj",):
        bpy.ops.wm.obj_import(filepath=path)
    elif ext in (".stl",):
        bpy.ops.wm.stl_import(filepath=path)
    else:
        raise SystemExit("不支持的模型格式: " + ext)

def mesh_objects():
    """功能: 取场景中全部网格对象. 参数: 无. 返回值: list"""
    return [o for o in bpy.data.objects if o.type == "MESH"]

def scene_stats():
    """功能: 统计场景规模. 参数: 无. 返回值: dict"""
    tris = 0
    for o in mesh_objects():
        tris += sum(max(len(p.vertices) - 2, 0) for p in o.data.polygons)
    return {
        "objects": len(bpy.data.objects),
        "meshes": len(mesh_objects()),
        "triangles": tris,
        "materials": len(bpy.data.materials),
    }
'''


def script_inspect(model_path: str, name_filter: str = "", limit: int = 60) -> str:
    """
    功能: 生成"检查模型"脚本 —— 导入后回传场景统计与对象清单.
    参数:
        model_path: 模型路径
        name_filter: 名称子串过滤(不区分大小写), 空表示不过滤
        limit: 最多回传多少个对象
    返回值: str, Python 源码
    """
    return PRELUDE + f'''
load_model(r"{model_path}")

keyword = {name_filter!r}.lower()
items = []
for o in mesh_objects():
    if keyword and keyword not in o.name.lower():
        continue
    dims = [round(v, 4) for v in o.dimensions]
    items.append({{
        "name": o.name,
        "parent": o.parent.name if o.parent else None,
        "dimensions": dims,
        "polygons": len(o.data.polygons),
        "materials": [m.name for m in o.data.materials if m],
    }})

items.sort(key=lambda x: -x["polygons"])
emit({{
    "ok": True,
    "path": r"{model_path}",
    "stats": scene_stats(),
    "matched": len(items),
    "objects": items[:{limit}],
}})
'''


def script_render(
    model_path: str,
    output_path: str,
    width: int = 1280,
    height: int = 900,
    view: str = "iso",
    samples: int = 32,
) -> str:
    """
    功能: 生成"渲染预览图"脚本 —— 导入模型, 自动布光取景并渲染一张 PNG.

    渲染预览是 AI 自查模型的主要手段: 删减是否删过头、材质是否合理、装配朝向对不对,
    看一张图比读一堆统计数字直观得多.

    参数:
        model_path: 模型路径
        output_path: 输出 PNG 路径
        width / height: 分辨率
        view: 机位, 可选 iso / front / left / top
        samples: EEVEE 采样数
    返回值: str, Python 源码
    """
    directions = {
        "iso": (1.0, -1.2, 0.85),
        "front": (0.0, -2.0, 0.35),
        "left": (-2.0, 0.0, 0.35),
        "top": (0.0, -0.01, 2.2),
    }
    dx, dy, dz = directions.get(view, directions["iso"])

    return PRELUDE + f'''
from mathutils import Vector

load_model(r"{model_path}")

objs = mesh_objects()
if not objs:
    emit({{"ok": False, "error": "模型中没有网格对象"}})
    raise SystemExit(0)

# 计算整体包围盒, 用于自动取景与布光距离
lo = Vector((float("inf"),) * 3)
hi = Vector((float("-inf"),) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
        hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
center = (lo + hi) / 2
radius = max((hi - lo).length / 2, 1e-6)

# 相机
cam_data = bpy.data.cameras.new("PreviewCam")
cam = bpy.data.objects.new("PreviewCam", cam_data)
bpy.context.scene.collection.objects.link(cam)
cam.location = center + Vector(({dx}, {dy}, {dz})) * radius * 1.9
direction = center - cam.location
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

# 三点布光: 主光 + 补光 + 轮廓光, 与前端的深色控制台风保持一致的冷调
def add_light(name, kind, loc, energy, color):
    """功能: 添加一盏灯. 参数: 名称/类型/位置/强度/颜色. 返回值: None"""
    data = bpy.data.lights.new(name, type=kind)
    data.energy = energy
    data.color = color
    obj = bpy.data.objects.new(name, data)
    obj.location = center + Vector(loc) * radius
    d = center - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(obj)

add_light("Key", "SUN", (1.2, -1.0, 1.6), 4.0, (0.86, 0.92, 1.0))
add_light("Fill", "SUN", (-1.4, 0.8, 0.6), 1.6, (0.42, 0.55, 0.78))
add_light("Rim", "SUN", (0.0, 1.6, 0.5), 2.2, (0.55, 0.72, 1.0))

# 深色背景, 与前端舞台一致
world = bpy.data.worlds.new("PreviewWorld")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.04, 0.05, 0.08, 1.0)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.7
bpy.context.scene.world = world

scene = bpy.context.scene
scene.render.resolution_x = {width}
scene.render.resolution_y = {height}
scene.render.filepath = r"{output_path}"
scene.render.image_settings.file_format = "PNG"

# 不同 Blender 版本的 EEVEE 引擎标识不同, 逐个尝试
for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
    try:
        scene.render.engine = engine
        break
    except TypeError:
        continue
if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
    scene.eevee.taa_render_samples = {samples}

os.makedirs(os.path.dirname(r"{output_path}"), exist_ok=True)
bpy.ops.render.render(write_still=True)

emit({{
    "ok": True,
    "output": r"{output_path}",
    "exists": os.path.isfile(r"{output_path}"),
    "engine": scene.render.engine,
    "stats": scene_stats(),
    "bounds_m": {{
        "min": [round(v, 3) for v in lo],
        "max": [round(v, 3) for v in hi],
        "size": [round(v, 3) for v in (hi - lo)],
    }},
}})
'''
