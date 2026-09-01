# -*- coding: utf-8 -*-
"""
功能:
    InoProShop(CODESYS SP11) 常驻 worker 主体. 由 server.mjs 在文件头注入 4 个常量后,
    经 --runscript(必须带 UI, 不能 --noUI)启动. 打开工程并保持热, 轮询请求目录, 逐条执行
    read/write/compile/list/save 等操作, 把结果以原子方式写到响应目录, 供 Node MCP 读取.
协议:
    请求文件: <IPC_DIR>/requests/<id>.req.json  (UTF-8, {"op":..., "args":{...}})
    响应文件: <IPC_DIR>/responses/<id>.resp.json (ASCII-escaped JSON, {"ok":bool, "result"|"error":...})
    状态文件: <IPC_DIR>/worker.status         (worker 状态心跳)
    停止哨兵: <IPC_DIR>/worker.stop           (存在即优雅退出并关闭 IDE)
注入常量(server.mjs / codesys_ipc.py 文件头注入): IPC_DIR / PROJECT_PATH / POLL_SEC /
    COMPILE_CATEGORY / PLC_IP / IDLE_TIMEOUT_SEC (后两者 body 自带默认, 头部注入则覆盖;
    IDLE_TIMEOUT_SEC<=0 表示常驻永不自关; QUARANTINE_AGE_SEC 仅测试注入, 生产用默认)
返回:
    无(全部经文件 IPC 返回)
"""
import os, sys, time, json, codecs, traceback, hashlib, re, uuid

try:
    basestring
except NameError:  # Python 3 offline contract tests; InoProShop SP11 uses Python 2
    basestring = str

# 注入常量兜底: server.mjs / codesys_ipc.py 在文件头注入权威值(已注入则原样保留)。
# 任一注入方未同步新常量时, 此默认防 NameError(老头部缺 IDLE_TIMEOUT_SEC/PLC_IP 仍能起 worker)。
if "IDLE_TIMEOUT_SEC" not in globals():
    IDLE_TIMEOUT_SEC = 120
if "PLC_IP" not in globals():
    PLC_IP = ""
if "QUARANTINE_AGE_SEC" not in globals():
    QUARANTINE_AGE_SEC = 10.0
if "WORKER_PROTOCOL_VERSION" not in globals():
    WORKER_PROTOCOL_VERSION = 3
if "DEPLOY_AUTH_TTL_SEC" not in globals():
    DEPLOY_AUTH_TTL_SEC = 60.0
if "WORKER_BODY_SHA256" not in globals():
    WORKER_BODY_SHA256 = ""

# 接管标志 TTL 逃生阀(F8): manual_control=true 且 updated_at 距今超过该时长 → 视为过期(未接管)+告警。
# 缺 updated_at 的旧格式 = 永不过期(接管是人类属主, 禁按 pid 存活自动失效 — 945dc6f 语义)。
# 与 codesys_ipc.py MANUAL_CONTROL_TTL_SEC / server.mjs MANUAL_CONTROL_TTL_SEC 同值(秒)。
MANUAL_CONTROL_TTL_SEC = 86400

# F6: 连续读取失败达到该轮数才隔离(单次 Windows 瞬态共享冲突/杀软占句柄不误伤);
# 年龄门槛(QUARANTINE_AGE_SEC, quarantine_if_stale 内)仍为前置 — 太新的文件两个判据都不隔离。
QUARANTINE_FAIL_THRESHOLD = 3

REQ_DIR = os.path.join(IPC_DIR, "requests")
RESP_DIR = os.path.join(IPC_DIR, "responses")
STATUS_PATH = os.path.join(IPC_DIR, "worker.status")
STOP_PATH = os.path.join(IPC_DIR, "worker.stop")
SESSION_CONTROL_PATH = os.path.join(IPC_DIR, "session_control.json")
DEPLOY_GUARD_PATH = os.path.join(IPC_DIR, "deploy.guard.json")
DEPLOY_AUTH_DIR = os.path.join(IPC_DIR, "deploy-auth")
PHYSICAL_DEPLOY_LOCK_PATH = os.path.join(IPC_DIR, "deploy.physical.lock")
REQ_SUFFIX = ".req.json"
CLAIM_SUFFIX = ".claimed.json"
WORKER_INSTANCE_ID = uuid.uuid4().hex
DEPLOY_GUARD_BLOCKED_OPS = set((
    "write", "create", "save", "compile", "generate_code", "deploy",
))
DEPLOY_GUARD_PURPOSE_OPS = {
    "deploy": set(("compile", "save", "deploy")),
    "restore": set(),
}


def ensure_dirs():
    for d in (IPC_DIR, REQ_DIR, RESP_DIR, DEPLOY_AUTH_DIR):
        if not os.path.exists(d):
            try:
                os.makedirs(d)
            except Exception:
                pass


def write_json_atomic(path, obj):
    """原子写: 先写 .tmp 再 rename; Windows 下 rename 目标已存在会报错, 故先删旧.

    用 ensure_ascii=False(写 UTF-8 文件)保留中文并避开 CODESYS 自带 json 的
    py_encode_basestring_ascii 对某些中文 unicode 串触发的 ascii 编解码崩溃(deploy login
    报错/中文编译消息常见); 后端/MCP 均以 UTF-8 读回, 兼容。兜底退 ascii 转义再退 repr。
    """
    try:
        data = json.dumps(obj, ensure_ascii=False)
    except Exception:
        try:
            data = json.dumps(obj)  # 退 ascii 转义路径
        except Exception:
            data = unicode(repr(obj))
    tmp = path + ".tmp"
    f = codecs.open(tmp, "w", "utf-8")
    f.write(data if isinstance(data, unicode) else unicode(data))
    f.close()
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    os.rename(tmp, path)


def write_status(state, extra=None):
    # pid 写入状态文件: 多客户端按 (state==ready and pid 存活) 判活并 attach 共享实例, 不依赖谁是父进程
    obj = {
        "state": state,
        "project": os.path.normcase(os.path.abspath(PROJECT_PATH)),
        "plc_ip": unicode(_injected_plc_ip()),
        "instance_id": WORKER_INSTANCE_ID,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "worker_body_sha256": WORKER_BODY_SHA256,
        "ts": time.time(),
        "pid": os.getpid(),
    }
    if extra:
        obj.update(extra)
    try:
        write_json_atomic(STATUS_PATH, obj)
    except Exception:
        pass


# ---------- 领域工具 ----------
def obj_name(o):
    try:
        return o.get_name()
    except Exception:
        try:
            return o.get_name(False)
        except Exception:
            return None


def has_attr_true(o, attr):
    try:
        return bool(getattr(o, attr))
    except Exception:
        return False


def find_app(project):
    try:
        app = project.active_application
        if app:
            return app
    except Exception:
        pass
    try:
        hits = list(project.find("Application", True))
        if hits:
            return hits[0]
    except Exception:
        pass
    return None


def find_by_path(project, full_path):
    """按 'Application/Folder/POU' 路径定位(斜杠或点分隔; 首段可为 Application 名; 末段失败回退递归 find)."""
    norm = full_path.replace("\\", "/").strip("/").replace(".", "/")
    parts = [p for p in norm.split("/") if p]
    if not parts:
        return None
    app = find_app(project)
    app_name = (obj_name(app) or "Application").lower() if app else ""
    current = project
    if app and parts[0].lower() == app_name:
        current = app
        parts = parts[1:]
        if not parts:
            return app
    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        found = None
        try:
            for child in current.get_children(False):
                if obj_name(child) == part:
                    found = child
                    break
        except Exception:
            pass
        if (found is None) and is_last:
            try:
                rec = list(current.find(part, True))
                if rec:
                    found = rec[0]
            except Exception:
                pass
        if found is None:
            return None
        current = found
    return current


def walk_pous(node, prefix, out, want_textual):
    try:
        children = list(node.get_children(False))
    except Exception:
        children = []
    for child in children:
        nm = obj_name(child)
        if nm is None:
            continue
        path = (prefix + "/" + nm) if prefix else nm
        has_impl = has_attr_true(child, "has_textual_implementation")
        has_decl = has_attr_true(child, "has_textual_declaration")
        if (not want_textual) or has_impl or has_decl:
            out.append({"path": path, "name": nm, "has_impl": has_impl, "has_decl": has_decl})
        walk_pous(child, path, out, want_textual)


def walk_tree(node, prefix, out, depth):
    """从工程根递归遍历完整设备树(含硬件节点), 产出预序展开列表.

    功能:
        与 walk_pous 同形, 但不做 textual 过滤, 并带 depth/has_children, 供上位机
        web「设备」标签按 InoProShop 设备树原序逐级渲染(硬件节点只展开, 程序节点可点开编辑)
    参数:
        node: 当前对象(首层传 project 根); prefix: 已累积的斜杠路径; out: 结果列表(就地追加);
        depth: 当前层级深度(根的直接子级为 0)
    返回:
        无(结果就地写入 out)
    """
    try:
        children = list(node.get_children(False))
    except Exception:
        children = []
    for child in children:
        nm = obj_name(child)
        if nm is None:
            continue
        path = (prefix + "/" + nm) if prefix else nm
        # 探测是否可展开(有无子级), 兄弟顺序即 get_children 的 InoProShop 树序
        try:
            kids = list(child.get_children(False))
        except Exception:
            kids = []
        out.append({"path": path, "name": nm, "depth": depth,
                    "has_impl": has_attr_true(child, "has_textual_implementation"),
                    "has_decl": has_attr_true(child, "has_textual_declaration"),
                    "has_children": len(kids) > 0})
        walk_tree(child, path, out, depth + 1)


# ---------- 操作 ----------
def op_status(project, args):
    return {
        "state": "ready",
        "project": os.path.normcase(os.path.abspath(PROJECT_PATH)),
        "plc_ip": unicode(_injected_plc_ip()),
        "instance_id": WORKER_INSTANCE_ID,
        "protocol_version": WORKER_PROTOCOL_VERSION,
    }


def op_list(project, args):
    want_textual = args.get("textual_only", True)
    app = find_app(project)
    root = app if app else project
    prefix = obj_name(app) if app else ""
    out = []
    walk_pous(root, prefix, out, want_textual)
    return {"pous": out, "count": len(out)}


def op_tree(project, args):
    out = []
    walk_tree(project, "", out, 0)  # 从工程根走, 不做 textual 过滤 -> 含硬件节点
    return {"nodes": out, "count": len(out)}


def op_read(project, args):
    path = args["path"]
    obj = find_by_path(project, path)
    if obj is None:
        raise RuntimeError("POU 未找到: %s" % path)
    decl = u""
    impl = u""
    if has_attr_true(obj, "has_textual_declaration"):
        decl = obj.textual_declaration.text
    if has_attr_true(obj, "has_textual_implementation"):
        impl = obj.textual_implementation.text
    return {"path": path, "name": obj_name(obj), "declaration": decl, "implementation": impl,
            "has_decl": has_attr_true(obj, "has_textual_declaration"),
            "has_impl": has_attr_true(obj, "has_textual_implementation")}


def op_write(project, args):
    path = args["path"]
    obj = find_by_path(project, path)
    if obj is None:
        raise RuntimeError("POU 未找到: %s" % path)
    updated = []
    decl = args.get("declaration", None)
    impl = args.get("implementation", None)
    if decl is not None and has_attr_true(obj, "has_textual_declaration"):
        obj.textual_declaration.replace(decl)
        updated.append("declaration")
    if impl is not None and has_attr_true(obj, "has_textual_implementation"):
        obj.textual_implementation.replace(impl)
        updated.append("implementation")
    saved = False
    if args.get("save", False) and updated:
        project.save()
        saved = True
    return {"path": path, "updated": updated, "saved": saved}


_CAPS_DEFAULT_PROBE = (
    "create_action", "create_pou", "create_method", "create_property",
    "create_transition", "create_dut", "create_gvl", "create_folder",
    "textual_declaration", "textual_implementation", "remove", "rename",
)


def op_caps(project, args):
    """探测某对象暴露了哪些 ScriptEngine 成员(只读).

    功能:
        确认 create_action / create_pou 等工厂方法在本机 InoProShop 分支上是否存在。
        ScriptEngine API 因 CODESYS 版本/汇川分支而异, 仓库内无先例可查(参考在
        D:\\InoProShop\\CODESYS\\Online Help\\ScriptEngine.chm), 故留此只读探针, 免得
        靠猜方法名去写会改工程的 op。
    参数:
        args["path"]:  对象路径, 同 op_read
        args["probe"]: 可选, 额外要 hasattr 探测的名字列表(与默认表合并)
    返回:
        {"path","name","members","probed"};
        members = dir() 结果(**ScriptEngine 是动态代理, 这里常常是空表, 不能据此判定不存在**),
        probed  = {名字: bool} 的 hasattr 实测, 这才是权威判据。
    """
    path = args["path"]
    obj = find_by_path(project, path)
    if obj is None:
        raise RuntimeError("对象未找到: %s" % path)
    names = list(_CAPS_DEFAULT_PROBE) + list(args.get("probe") or [])
    probed = {}
    for n in names:
        try:
            probed[n] = hasattr(obj, n)
        except Exception:
            probed[n] = False
    return {"path": path, "name": obj_name(obj),
            "members": sorted([m for m in dir(obj) if not m.startswith("_")]),
            "probed": probed}


def _create_child(parent, kind, name, language):
    """在 parent 下建一个 action/pou 子对象, 吸收各版本 language 形参差异.

    ScriptEngine 的 create_action/create_pou 在不同版本里 language 可选或必填; 省略时
    继承父 POU 的实现语言(FeedLift_L2 等均为 ST), 正是我们想要的默认。故按
    "不传 → 传 None" 两级回退, 不去猜 ImplementationLanguages 枚举在本分支的确切名字。
    """
    factory = parent.create_action if kind == "action" else parent.create_pou
    if language is not None:
        return factory(name, language)
    try:
        return factory(name)
    except TypeError:
        return factory(name, None)


def op_create(project, args):
    """在已有 POU 下新建 Action(或在 Application 下新建 POU).

    功能:
        补上 op_write 的空缺 —— write 只能改已存在的对象, 新增原子动作(如 FeedLift_L2 下
        的 A13_feed_clear)此前只能人工在 InoProShop 里点。建完的对象正文为空, 由随后的
        write 填 ST。
    参数:
        args["parent"]: 父对象路径, 如 Application/50_action/FeedLift_L2
        args["name"]:   新对象名, 如 A13_feed_clear
        args["kind"]:   action(默认) | pou
        args["language"]: 可选, 显式实现语言; 省略即继承父对象语言
        args["save"]:   是否立即 project.save(), 默认 False
    返回:
        {"path","name","created","saved","has_decl","has_impl"};
        同名对象已存在时 created=False 原样返回 —— IPC 允许重投递, 建对象必须幂等。
    """
    parent_path = args["parent"]
    name = args["name"]
    kind = args.get("kind") or "action"
    if kind not in ("action", "pou"):
        raise RuntimeError("kind 应为 action|pou, 收到 %r" % kind)
    parent = find_by_path(project, parent_path)
    if parent is None:
        raise RuntimeError("父对象未找到: %s" % parent_path)

    full = parent_path.rstrip("/") + "/" + name
    existing = find_by_path(project, full)
    if existing is not None:
        return {"path": full, "name": obj_name(existing), "created": False, "saved": False,
                "has_decl": has_attr_true(existing, "has_textual_declaration"),
                "has_impl": has_attr_true(existing, "has_textual_implementation")}

    obj = _create_child(parent, kind, name, args.get("language"))
    saved = False
    if args.get("save", False):
        project.save()
        saved = True
    return {"path": full, "name": obj_name(obj), "created": True, "saved": saved,
            "has_decl": has_attr_true(obj, "has_textual_declaration"),
            "has_impl": has_attr_true(obj, "has_textual_implementation")}


def _collect_compile_messages():
    """Collect the current compiler-category messages without starting a build."""
    errors = []
    warnings = []
    info_count = 0
    try:
        msgs = list(system.get_message_objects(COMPILE_CATEGORY))
    except Exception:
        msgs = []
    for m in msgs:
        try:
            sev = unicode(getattr(m, "severity", u""))
        except Exception:
            sev = u""
        try:
            txt = unicode(getattr(m, "text", u""))
        except Exception:
            txt = u""
        rec = {"severity": sev, "text": txt}
        low = sev.lower()
        if "error" in low:
            errors.append(rec)
        elif "warning" in low:
            warnings.append(rec)
        else:
            info_count += 1
    return {"error_count": len(errors), "warning_count": len(warnings), "info_count": info_count,
            "errors": errors, "warnings": warnings}


def op_compile(project, args):
    app = find_app(project)
    if app is None:
        raise RuntimeError("工程内未找到可编译的 Application")
    try:
        system.clear_messages(COMPILE_CATEGORY)
    except Exception:
        pass
    app.build()
    return _collect_compile_messages()


def _symbol_xml_paths(app):
    """Return Symbol Configuration XML candidates for the active application.

    CODESYS names the generated file as
    ``<project>.<device>.<application>.xml``.  Prefer that exact name, but retain
    a header-checked directory scan for vendor profiles whose device hierarchy
    cannot be inspected through ScriptEngine.
    """
    project_path = os.path.abspath(PROJECT_PATH)
    project_dir = os.path.dirname(project_path)
    project_name = os.path.splitext(os.path.basename(project_path))[0]
    app_name = obj_name(app) or "Application"

    # The application normally sits below "PLC Logic" below the controller.
    # Keep the uppermost ScriptDeviceObject name so nested logical-device nodes
    # do not replace the physical device name used by CODESYS in the filename.
    device_name = None
    current = app
    for _ in range(32):
        if current is None:
            break
        if has_attr_true(current, "is_device"):
            nm = obj_name(current)
            if nm:
                device_name = nm
        try:
            parent = current.parent
        except Exception:
            break
        if parent is current:
            break
        current = parent

    paths = []
    if device_name:
        paths.append(os.path.join(
            project_dir, "%s.%s.%s.xml" % (project_name, device_name, app_name)))

    try:
        names = os.listdir(project_dir)
    except Exception:
        names = []
    prefix = project_name + "."
    suffix = "." + app_name + ".xml"
    for name in names:
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        path = os.path.join(project_dir, name)
        if path not in paths:
            paths.append(path)
    return paths


def _is_symbol_configuration_xml(path):
    try:
        f = open(path, "rb")
        try:
            head = f.read(4096)
        finally:
            f.close()
        return b"<Symbolconfiguration" in head
    except Exception:
        return False


def op_generate_code(project, args):
    """Generate the active application's Symbol Configuration XML offline.

    This operation intentionally calls only ``app.generate_code()``.  It never
    creates an online application and never calls login/download/deploy APIs.
    """
    app = find_app(project)
    if app is None:
        raise RuntimeError("工程内未找到可生成代码的 Application")

    before = {}
    for path in _symbol_xml_paths(app):
        try:
            st = os.stat(path)
            before[os.path.abspath(path)] = (st.st_mtime, st.st_size)
        except Exception:
            pass

    try:
        system.clear_messages(COMPILE_CATEGORY)
    except Exception:
        pass
    app.generate_code()
    messages = _collect_compile_messages()

    candidates = [os.path.abspath(p) for p in _symbol_xml_paths(app)
                  if _is_symbol_configuration_xml(p)]
    if not candidates:
        raise RuntimeError(
            "生成代码完成，但项目目录未找到 Symbolconfiguration XML；请确认工程包含 Symbols 对象")
    xml_path = max(candidates, key=lambda p: os.path.getmtime(p))
    stat = os.stat(xml_path)
    previous = before.get(xml_path)
    result = dict(messages)
    result.update({
        "generated": messages["error_count"] == 0,
        "xml_path": xml_path,
        "xml_mtime": stat.st_mtime,
        "xml_size": stat.st_size,
        "xml_changed": previous is None or previous != (stat.st_mtime, stat.st_size),
    })
    return result


def op_save(project, args):
    project.save()
    return {"saved": True}


# ---------- 部署 (全下载到真机; 不自动启动) ----------
_FORCE_FULL_CANDIDATES = ("Never", "ForceDownload", "Force", "FullDownload")


def resolve_force_full_option():
    """探测 OnlineChangeOption 的"强制全下载"枚举值(规避在线改/全下载 GUI 弹窗阻塞无人值守 worker).

    返回:
        (opt_value, opt_name); 未找到返回 (None, None). 枚举名在 SP11 未必叫 Never,
        故按候选逐一 getattr 尝试(以 spike_deploy.py 探测结果为准)。
    """
    try:
        enum = OnlineChangeOption  # CODESYS 脚本全局; 不存在则 NameError
    except NameError:
        return (None, None)
    for cand in _FORCE_FULL_CANDIDATES:
        try:
            return (getattr(enum, cand), cand)
        except Exception:
            continue
    return (None, None)


def _build_and_collect(app):
    """编译 Application 并收集错误/警告(下发前置门控; 与 op_compile 同语义, 独立留存避免改动已验证的 op_compile).

    返回:
        (error_count, errors, warnings); errors/warnings 为 [{"severity","text"}]
    """
    try:
        system.clear_messages(COMPILE_CATEGORY)
    except Exception:
        pass
    app.build()
    errors = []
    warnings = []
    try:
        msgs = list(system.get_message_objects(COMPILE_CATEGORY))
    except Exception:
        msgs = []
    for m in msgs:
        try:
            sev = unicode(getattr(m, "severity", u""))
        except Exception:
            sev = u""
        try:
            txt = unicode(getattr(m, "text", u""))
        except Exception:
            txt = u""
        low = sev.lower()
        if "error" in low:
            errors.append({"severity": sev, "text": txt})
        elif "warning" in low:
            warnings.append({"severity": sev, "text": txt})
    return (len(errors), errors, warnings)


def _injected_plc_ip():
    """取注入的真机 PLC IP(backend codesys_ipc 注入 PLC_IP 常量; MCP 未注入则 NameError -> 空串)."""
    try:
        return PLC_IP  # 注入常量
    except NameError:
        return ""


def get_gateway():
    """取网关对象: online.gateways['Gateway-1'](退路遍历/索引 0)."""
    try:
        gws = online.gateways
    except Exception:
        return None
    try:
        g = gws["Gateway-1"]
        if g is not None:
            return g
    except Exception:
        pass
    try:
        for g in gws:
            return g
    except Exception:
        pass
    try:
        return gws[0]
    except Exception:
        return None


def find_device(project):
    """定位唯一可设置且可回读通信地址的控制器设备节点."""
    candidates = []
    try:
        hits = list(project.find("Device", True))
        for h in hits:
            if (hasattr(h, "set_gateway_and_address")
                    and hasattr(h, "get_address")):
                candidates.append(h)
    except Exception:
        pass
    if not candidates:
        try:
            for obj in project.get_children(True):
                if (hasattr(obj, "set_gateway_and_address")
                        and hasattr(obj, "get_address")):
                    candidates.append(obj)
        except Exception:
            pass
    # Identity de-duplication: some ScriptEngine traversals return the same
    # device through both project.find and get_children.
    unique = []
    seen = set()
    for obj in candidates:
        marker = id(obj)
        if marker not in seen:
            seen.add(marker)
            unique.append(obj)
    if len(unique) != 1:
        raise RuntimeError(
            u"expected exactly one addressable PLC Device, found %d" % len(unique))
    return unique[0]


def set_comm_path_by_ip(project):
    """按 IP 单播(find_address_by_ip)设设备活动通信路径, 绕开 InoProShop 广播扫描.

    返回:
        unicode 说明(成功); None(无 PLC_IP / 取不到网关设备 / 方法不可用, 静默由后续 login 暴露)
    """
    plc_ip = _injected_plc_ip()
    if not plc_ip:
        return None
    gw = get_gateway()
    device = find_device(project)
    if gw is None or device is None:
        return None
    if hasattr(gw, "find_address_by_ip") and hasattr(device, "set_gateway_and_address"):
        addr = gw.find_address_by_ip(plc_ip)  # 单播定向查找(11740), 绕广播
        if addr is None:
            raise RuntimeError(u"find_address_by_ip(%s) returned None" % plc_ip)
        if not unicode(addr).strip():
            raise RuntimeError(u"find_address_by_ip(%s) returned an empty address" % plc_ip)
        device.set_gateway_and_address(gw, addr)
        current = device.get_address()
        if current is None:
            raise RuntimeError(u"device.get_address() returned None after target selection")
        if not unicode(current).strip():
            raise RuntimeError(u"device.get_address() returned an empty address after target selection")
        if current != addr and unicode(current) != unicode(addr):
            raise RuntimeError(
                u"active target readback mismatch: expected=%s, current=%s"
                % (unicode(addr), unicode(current)))
        return {
            "description": u"set_gateway_and_address(%s)=%s; readback=%s" % (
                plc_ip, unicode(addr), unicode(current)),
            "plc_ip": unicode(plc_ip),
            "address": unicode(addr),
        }
    return None


def verify_comm_path_readback(project, expected_address):
    """Re-read the exact device path immediately before physical login."""
    if not unicode(expected_address or u"").strip():
        return u"expected target address is empty"
    try:
        device = find_device(project)
        current = device.get_address()
    except Exception as exc:
        return u"target path readback failed: " + unicode(repr(exc))
    if current is None or not unicode(current).strip():
        return u"target path readback is empty"
    if unicode(current) != unicode(expected_address):
        return u"target path changed before login: expected=%s, current=%s" % (
            unicode(expected_address), unicode(current))
    return None


def op_online_status(project, args):
    """探测真机下发前置条件(创建 online application 句柄; 不登录、不碰运行态), 供 web 软门控下发按钮.

    说明:
        句柄可建表明工程有可下发 Application 且网关在工程内已配; 真正的链路可达性需 login(即 deploy 本身).
        运行态属性名以 spike 探测为准, 容错读取, 读不到则 None。
    返回:
        dict, {"ready":bool, "state":str|None, "reason":str|None}
    """
    app = find_app(project)
    if app is None:
        return {"ready": False, "state": None, "reason": u"工程内未找到 Application"}
    try:
        oa = online.create_online_application(app)
    except Exception as exc:
        return {"ready": False, "state": None, "reason": unicode(repr(exc))}
    state = None
    for attr in ("application_state", "state"):
        try:
            v = getattr(oa, attr)
            if v is not None:
                state = unicode(v)
                break
        except Exception:
            continue
    return {"ready": True, "state": state, "reason": None}


def _file_sha256(path):
    h = hashlib.sha256()
    f = open(path, "rb")
    try:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    finally:
        f.close()
    return h.hexdigest()


def _deploy_rejected(reason, **extra):
    result = {
        "deployed": False,
        "started": False,
        "boot_written": False,
        "authorization_valid": False,
        "retryable": False,
        "reason": unicode(reason),
    }
    result.update(extra)
    return result


def _deploy_authorization_error(ticket, expected_project_sha=None):
    """Return a fail-closed reason, or None while the consumed ticket is valid."""
    if not isinstance(ticket, dict):
        return u"deploy authorization ticket is unreadable"
    nonce = ticket.get("nonce")
    if not isinstance(nonce, basestring) or not re.match(r"^[0-9a-f]{48}$", nonce):
        return u"invalid deploy authorization nonce"
    consumed = read_json_file(os.path.join(
        DEPLOY_AUTH_DIR, nonce + ".consumed.json"))
    if not isinstance(consumed, dict):
        return u"consumed deploy authorization is missing or unreadable"
    fields = (
        "nonce", "issued_at", "expires_at", "worker_instance_id", "guard_token",
        "expected_sha256", "expected_plc_ip", "commit_seq", "protocol_version",
        "worker_body_sha256",
    )
    for name in fields:
        if consumed.get(name) != ticket.get(name):
            return u"consumed deploy authorization changed: " + unicode(name)

    guard = read_json_file(DEPLOY_GUARD_PATH)
    now = time.time()
    try:
        issued_at = float(ticket.get("issued_at"))
        expires_at = float(ticket.get("expires_at"))
        commit_seq = int(ticket.get("commit_seq"))
        protocol_version = int(ticket.get("protocol_version"))
        guard_protocol = int(guard.get("protocol_version", 0) or 0)
    except Exception:
        return u"deploy authorization or guard has invalid scalar fields"
    sha = unicode(ticket.get("expected_sha256") or u"").lower()
    target_ip = unicode(ticket.get("expected_plc_ip") or u"").strip()
    guard_token = guard.get("token") if isinstance(guard, dict) else None
    duration = expires_at - issued_at
    valid = (
        isinstance(guard, dict)
        and guard.get("state") == "active"
        and guard.get("purpose") == "deploy"
        and isinstance(guard_token, basestring)
        and bool(re.match(r"^[0-9a-f]{48}$", guard_token))
        and guard_token == ticket.get("guard_token")
        and guard.get("project") == os.path.normcase(os.path.abspath(PROJECT_PATH))
        and unicode(guard.get("plc_ip") or u"") == target_ip
        and guard_protocol == WORKER_PROTOCOL_VERSION
        and guard.get("worker_body_sha256") == WORKER_BODY_SHA256
        and ticket.get("worker_instance_id") == WORKER_INSTANCE_ID
        and protocol_version == WORKER_PROTOCOL_VERSION
        and ticket.get("worker_body_sha256") == WORKER_BODY_SHA256
        and issued_at <= now + 5.0
        and expires_at >= now
        and duration > 0.0
        and duration <= float(DEPLOY_AUTH_TTL_SEC) + 0.001
        and commit_seq > 0
        and bool(target_ip)
        and target_ip == unicode(_injected_plc_ip())
        and bool(re.match(r"^[0-9a-f]{64}$", sha))
    )
    if not valid:
        return u"deploy authorization expired or is not bound to this worker/project/PLC/commit"
    if expected_project_sha is not None:
        current_sha = unicode(_file_sha256(PROJECT_PATH)).lower()
        if current_sha != unicode(expected_project_sha).lower() or current_sha != sha:
            return u"project SHA-256 changed before login"
    return None


def acquire_physical_deploy_lock(ticket):
    """Atomically enter the final validation/login critical section."""
    token = uuid.uuid4().hex
    payload = {
        "owner": "codesys-worker",
        "purpose": "physical_deploy",
        "owner_pid": os.getpid(),
        "owner_token": token,
        "worker_instance_id": WORKER_INSTANCE_ID,
        "worker_body_sha256": WORKER_BODY_SHA256,
        "authorization_nonce": ticket.get("nonce"),
        "created_at": time.time(),
    }
    try:
        fd = os.open(
            PHYSICAL_DEPLOY_LOCK_PATH,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
    except Exception:
        return None
    try:
        os.write(fd, json.dumps(payload).encode("utf-8"))
    finally:
        os.close(fd)
    return token


def release_physical_deploy_lock(token):
    held = read_json_file(PHYSICAL_DEPLOY_LOCK_PATH)
    if not isinstance(held, dict) or held.get("owner_token") != token:
        return False
    try:
        os.remove(PHYSICAL_DEPLOY_LOCK_PATH)
        return True
    except Exception:
        return False


def physical_deploy_lock_owned(token):
    held = read_json_file(PHYSICAL_DEPLOY_LOCK_PATH)
    try:
        owner_pid = int(held.get("owner_pid", 0) or 0)
    except Exception:
        owner_pid = 0
    return (isinstance(held, dict)
            and held.get("owner_token") == token
            and owner_pid == os.getpid()
            and held.get("worker_instance_id") == WORKER_INSTANCE_ID)


def consume_deploy_authorization(args):
    """Atomically consume and validate a one-shot deploy ticket before any PLC access.

    The pending→consumed rename is the durable replay barrier.  A worker crash after
    this point leaves a consumed file; no restarted worker can use the nonce again.
    """
    auth = (args or {}).get("authorization")
    if not isinstance(auth, dict):
        return (None, _deploy_rejected(u"missing deploy authorization"))
    nonce = auth.get("nonce")
    if not isinstance(nonce, basestring) or not re.match(r"^[0-9a-f]{48}$", nonce):
        return (None, _deploy_rejected(u"invalid deploy authorization nonce"))
    pending = os.path.join(DEPLOY_AUTH_DIR, nonce + ".pending.json")
    consumed = os.path.join(DEPLOY_AUTH_DIR, nonce + ".consumed.json")
    try:
        os.rename(pending, consumed)  # atomic one-shot claim; failure means used/revoked/missing
    except Exception:
        return (None, _deploy_rejected(u"deploy authorization is missing, revoked, or already consumed"))
    ticket = read_json_file(consumed)
    if not isinstance(ticket, dict):
        return (None, _deploy_rejected(u"deploy authorization ticket is unreadable"))

    fields = (
        "nonce", "issued_at", "expires_at", "worker_instance_id", "guard_token",
        "expected_sha256", "expected_plc_ip", "commit_seq", "protocol_version",
        "worker_body_sha256",
    )
    for name in fields:
        if ticket.get(name) != auth.get(name):
            return (None, _deploy_rejected(u"deploy authorization payload mismatch: " + unicode(name)))

    reason = _deploy_authorization_error(ticket)
    if reason is not None:
        return (None, _deploy_rejected(reason))
    return (ticket, None)


def op_deploy(project, args):
    """全下载工程到真机并自动启动: 按 IP 单播设活动路径(绕广播扫描) → build(0 错才继续) →
       login(强制全下载, PLC 进 STOP) → start(自动启动, PLC 运行新程序) → logout.

    设计要点(均由真机验证得出):
      - set_comm_path_by_ip: find_address_by_ip 单播定向, 绕开本机多网卡使广播扫描失效的问题;
        无 PLC_IP 注入则跳过(依赖 GUI 已设活动路径)。
      - create_online_application 无参优先(论坛示例), 退带 app 参数。
      - 启动: login(Never,True) 全下载本身即自动启动应用; 泵消息循环让在线态落定后 oa.start() 兜底,
        若已在运行(报 "...state is run")即视作 started 成功; 真异常置 start_error(不影响 deployed)。
      - 断电保活/引导应用: 由设备「启动应用设置→下载创建默认应用」在全下载时自动创建(已确认勾选),
        故不再脚本显式 create_boot_application(该调用在此 SP11 恒 NullReference 且冗余)。
      - 编译有错即中止(不进 login); login 抛错由 dispatch 兜成 502(真机未改写)。
    返回:
        dict, {"deployed":bool, "started":bool, "boot_implicit":True, "error_count":n,
               "set_path":str|None, "start_error":str|None, ...}
    """
    authorization, rejected = consume_deploy_authorization(args)
    if rejected is not None:
        return rejected
    expected_sha = unicode(authorization["expected_sha256"]).lower()
    target_ip = unicode(authorization["expected_plc_ip"])
    commit_seq = int(authorization["commit_seq"])

    # The host compiles, saves, snapshots, and then creates the deploy guard before
    # issuing this one-shot authorization.  Do not call project.save() here:
    # InoProShop rewrites volatile container metadata on every save, even when no
    # POU changed, so a second save would invalidate the exact authorized bytes.
    # The shared guard blocks every writer while this disk hash is checked again.
    try:
        actual_sha = unicode(_file_sha256(PROJECT_PATH)).lower()
    except Exception as exc:
        return _deploy_rejected(
            u"project hash failed before login: " + unicode(repr(exc)),
            authorization_valid=True, project_sha256=None, target_ip=target_ip,
            commit_seq=commit_seq,
        )
    if actual_sha != expected_sha:
        return _deploy_rejected(
            u"project SHA-256 changed after authorization; login blocked",
            authorization_valid=True, project_sha256=actual_sha,
            expected_sha256=expected_sha, target_ip=target_ip, commit_seq=commit_seq,
            stage="project_hash_mismatch",
        )

    app = find_app(project)
    if app is None:
        return _deploy_rejected(
            u"工程内未找到可下发的 Application", authorization_valid=True,
            project_sha256=actual_sha, target_ip=target_ip, commit_seq=commit_seq,
        )
    try:
        error_count, errors, warnings = _build_and_collect(app)
    except Exception as exc:
        return _deploy_rejected(
            u"build failed before login: " + unicode(repr(exc)),
            authorization_valid=True, project_sha256=actual_sha,
            target_ip=target_ip, commit_seq=commit_seq, stage="build_failed",
        )
    if error_count > 0:
        return {"deployed": False, "boot_written": False, "started": False,
                "error_count": error_count, "errors": errors, "warnings": warnings,
                "authorization_valid": True, "project_sha256": actual_sha,
                "target_ip": target_ip, "commit_seq": commit_seq,
                "reason": u"编译未通过, 已中止下发"}
    opt, opt_name = resolve_force_full_option()
    if opt is None:
        return _deploy_rejected(
            u"未找到强制全下载选项(OnlineChangeOption)，login 已阻断",
            authorization_valid=True, project_sha256=actual_sha,
            target_ip=target_ip, commit_seq=commit_seq, stage="login_option_missing",
        )

    # 自动下载绝不沿用 GUI 上一次活动路径。必须按授权 IP 单播定向成功才允许 login。
    try:
        set_path_info = set_comm_path_by_ip(project)
    except Exception as exc:
        return _deploy_rejected(
            u"set communication path failed before login: " + unicode(repr(exc)),
            authorization_valid=True, project_sha256=actual_sha,
            target_ip=target_ip, commit_seq=commit_seq, target_verified=False,
        )
    if not set_path_info:
        return _deploy_rejected(
            u"target PLC path could not be verified; login blocked",
            authorization_valid=True, project_sha256=actual_sha,
            target_ip=target_ip, commit_seq=commit_seq, target_verified=False,
        )

    physical_lock_token = acquire_physical_deploy_lock(authorization)
    if not physical_lock_token:
        return _deploy_rejected(
            u"physical deploy critical section is already active or outcome-unknown; login blocked",
            authorization_valid=False, project_sha256=actual_sha,
            target_ip=target_ip, commit_seq=commit_seq,
            stage="physical_deploy_locked", login_attempted=False,
        )
    deploy_result = None
    locked_path_info = None
    try:
        # Re-select the authorized IP while holding the physical barrier, then
        # create the online handle against that path.  Never reuse a GUI path or
        # an online handle created before the critical section.
        try:
            locked_path_info = set_comm_path_by_ip(project)
        except Exception as exc:
            deploy_result = _deploy_rejected(
                u"final target selection failed before login: " + unicode(repr(exc)),
                authorization_valid=False, project_sha256=actual_sha,
                target_ip=target_ip, commit_seq=commit_seq,
                stage="final_target_verification_failed", login_attempted=False,
            )
        if deploy_result is None and not isinstance(locked_path_info, dict):
            deploy_result = _deploy_rejected(
                u"final target selection returned no address binding",
                authorization_valid=False, project_sha256=actual_sha,
                target_ip=target_ip, commit_seq=commit_seq,
                stage="final_target_verification_failed", login_attempted=False,
            )
        if deploy_result is None:
            try:
                oa = online.create_online_application()
                if oa is None:
                    oa = online.create_online_application(app)
            except Exception:
                try:
                    oa = online.create_online_application(app)
                except Exception as exc:
                    deploy_result = _deploy_rejected(
                        u"online application creation failed before login: " + unicode(repr(exc)),
                        authorization_valid=False, project_sha256=actual_sha,
                        target_ip=target_ip, commit_seq=commit_seq,
                        stage="online_handle_failed", login_attempted=False,
                    )
        if deploy_result is None:
            target_error = verify_comm_path_readback(
                project, locked_path_info.get("address"))
            if target_error is not None:
                deploy_result = _deploy_rejected(
                    target_error, authorization_valid=False, project_sha256=actual_sha,
                    target_ip=target_ip, commit_seq=commit_seq,
                    stage="final_target_verification_failed", login_attempted=False,
                )
        if deploy_result is None:
            # Final check immediately before login. The physical lock prevents Host
            # reconciliation from clearing the guard between this check and the
            # non-idempotent controller write.
            final_error = _deploy_authorization_error(
                authorization, expected_project_sha=actual_sha)
            if final_error is not None:
                deploy_result = _deploy_rejected(
                    final_error, authorization_valid=False, project_sha256=actual_sha,
                    target_ip=target_ip, commit_seq=commit_seq,
                    stage="final_authorization_failed", login_attempted=False,
                )
        if deploy_result is None and not physical_deploy_lock_owned(physical_lock_token):
            deploy_result = _deploy_rejected(
                u"physical deploy lock ownership was lost before login",
                authorization_valid=False, project_sha256=actual_sha,
                target_ip=target_ip, commit_seq=commit_seq,
                stage="physical_deploy_lock_lost", login_attempted=False,
            )

        if deploy_result is None:
            oa.login(opt, True)  # 强制全下载: PLC 进入 STOP(不走在线改, 规避 GUI 弹窗阻塞)

            # 全下载后泵消息循环让在线态落定, 再自动启动; start best-effort(失败不影响 deployed, 置 started/start_error)
            # 引导/断电保活由设备「下载创建默认应用」在全下载时自动建, 不再脚本显式写
            started = False
            start_error = None
            try:
                for _ in range(20):
                    try:
                        system.process_messageloop()
                    except Exception:
                        pass
                    time.sleep(0.1)
                oa.start()  # 启动: PLC 运行新程序
                started = True
            except Exception as exc:
                emsg = unicode(repr(exc))
                # 全下载已使应用进入运行(login True 即下载后自动启动)→ start 报"已在运行", 视作启动成功
                if "is run" in emsg.lower():
                    started = True
                else:
                    start_error = emsg
            try:
                oa.logout()  # 断开(程序留在 PLC 运行)
            except Exception:
                pass
            deploy_result = {
                "deployed": True, "started": started, "boot_implicit": True,
                "error_count": 0, "warning_count": len(warnings),
                "login_option": opt_name, "set_path": locked_path_info,
                "start_error": start_error, "authorization_valid": True,
                "project_sha256": actual_sha, "target_ip": target_ip,
                "target_verified": True, "commit_seq": commit_seq,
                "worker_body_sha256": WORKER_BODY_SHA256,
                "login_attempted": True,
            }
    finally:
        physical_lock_released = release_physical_deploy_lock(physical_lock_token)
    deploy_result["physical_lock_released"] = physical_lock_released
    if not physical_lock_released:
        deploy_result.update({
            "ready": False,
            "retryable": False,
            "maintenance_recovery_required": True,
            "stage": "physical_lock_release_failed",
            "reason": u"physical deploy completed or was blocked, but its critical-section lock could not be released",
        })
    return deploy_result


OPS = {
    "status": op_status,
    "list": op_list,
    "tree": op_tree,
    "read": op_read,
    "write": op_write,
    "caps": op_caps,
    "create": op_create,
    "compile": op_compile,
    "generate_code": op_generate_code,
    "save": op_save,
    "online_status": op_online_status,
    "deploy": op_deploy,
}


def dispatch(project, req):
    op = req.get("op")
    args = req.get("args") or {}
    fn = OPS.get(op)
    if fn is None:
        return {"ok": False, "error": "未知操作: %s" % op}
    try:
        return {"ok": True, "result": fn(project, args)}
    except Exception as exc:
        return {"ok": False, "error": unicode(repr(exc)), "trace": unicode(traceback.format_exc())}


def read_json_file(path):
    """读 JSON 文件(UTF-8 + 剥 BOM); 缺失/半写入/坏 JSON 一律返回 None.

    read_request / read_manual_control 共用(F9: BOM 剥离是 2026-07 毒文件事故的核心,
    后续读取加固只落一处)。与 codesys_ipc._read_json(utf-8-sig) / server.mjs readJson
    (剥 \\ufeff) 同语义镜像。
    """
    try:
        f = codecs.open(path, "r", "utf-8")
        raw = f.read()
        f.close()
        # 剥 BOM: PowerShell/记事本手工写入的文件常带 U+FEFF, 不剥则 json.loads 永远失败
        return json.loads(raw.lstrip(u"\ufeff"))
    except Exception:
        return None


def read_request(reqpath):
    req = read_json_file(reqpath)   # None = 可能是半写入, 本轮跳过(不删, 下轮再试)
    if not isinstance(req, dict):
        return None                 # 非 dict 的合法 JSON(如数组)同样视为坏请求, 走隔离路径
    return req


def deploy_guard_allows(req):
    """Worker-side enforcement for clients that do not know the shared guard protocol."""
    op = req.get("op")
    if op not in DEPLOY_GUARD_BLOCKED_OPS:
        return (True, None)
    guard = read_json_file(DEPLOY_GUARD_PATH)
    if not isinstance(guard, dict):
        if os.path.exists(DEPLOY_GUARD_PATH):
            return (False, u"deploy guard is unreadable; mutation blocked fail-closed")
        return (True, None)
    if guard.get("state") != "active":
        return (False, u"invalid deploy guard state; mutation blocked fail-closed")
    guard_token = guard.get("token")
    if (not isinstance(guard_token, basestring)
            or not re.match(r"^[0-9a-f]{48}$", guard_token)):
        return (False, u"deploy guard token is missing or invalid")
    if req.get("deploy_guard_token") != guard_token:
        return (False, u"active PLC project/deploy transaction blocks operation '%s'" % op)
    if op not in DEPLOY_GUARD_PURPOSE_OPS.get(guard.get("purpose"), set()):
        return (False, u"deploy guard purpose '%s' does not authorize operation '%s'"
                % (guard.get("purpose"), op))
    if guard.get("project") != os.path.normcase(os.path.abspath(PROJECT_PATH)):
        return (False, u"deploy guard project fingerprint mismatch")
    if unicode(guard.get("plc_ip") or u"") != unicode(_injected_plc_ip()):
        return (False, u"deploy guard PLC target fingerprint mismatch")
    try:
        if int(guard.get("protocol_version", 0) or 0) != WORKER_PROTOCOL_VERSION:
            return (False, u"deploy guard protocol fingerprint mismatch")
    except Exception:
        return (False, u"deploy guard protocol fingerprint is invalid")
    if guard.get("worker_body_sha256") != WORKER_BODY_SHA256:
        return (False, u"deploy guard worker-build fingerprint mismatch")
    return (True, None)


def stop_guard_allows():
    guard = read_json_file(DEPLOY_GUARD_PATH)
    if not isinstance(guard, dict):
        return not os.path.exists(DEPLOY_GUARD_PATH)
    request = read_json_file(STOP_PATH)
    guard_token = guard.get("token")
    return (
        isinstance(request, dict)
        and guard.get("state") == "active"
        and guard.get("purpose") == "restore"
        and isinstance(guard_token, basestring)
        and bool(re.match(r"^[0-9a-f]{48}$", guard_token))
        and request.get("deploy_guard_token") == guard_token
    )


def reject_abandoned_deploy_claims():
    """Never replay a deploy atomically claimed by a previous worker instance."""
    try:
        files = [f for f in os.listdir(REQ_DIR) if f.endswith(CLAIM_SUFFIX)]
    except Exception:
        files = []
    for fn in files:
        rid = fn[:-len(CLAIM_SUFFIX)]
        claimpath = os.path.join(REQ_DIR, fn)
        req = read_request(claimpath)
        if not isinstance(req, dict) or req.get("op") != "deploy":
            continue
        resppath = os.path.join(RESP_DIR, rid + ".resp.json")
        if not os.path.exists(resppath):
            try:
                write_json_atomic(resppath, {
                    "ok": False,
                    "error": "previous worker left a claimed deploy request; outcome is unknown and replay is forbidden",
                })
            except Exception:
                continue
        try:
            os.remove(claimpath)
        except Exception:
            pass


def quarantine_if_stale(reqpath):
    """把超龄的坏请求文件改名 .bad 隔离; 返回 True=已隔离.

    调用点(main 循环)已用连败计数(QUARANTINE_FAIL_THRESHOLD)守门 — 只有连续
    QUARANTINE_FAIL_THRESHOLD 轮读取失败的文件才会走到这里; 本函数保留年龄门槛作前置:
    半写入文件毫秒级内即写完, 未满 QUARANTINE_AGE_SEC 的文件即使连败也不隔离(F6)。
    不隔离则坏文件永久滞留 requests/: 主循环永远走非空分支 -> 满速空转
    (2026-07 真实事故: 一个带 BOM 的手工请求让 InoProShop 永不释放工程锁)。
    """
    try:
        if time.time() - os.path.getmtime(reqpath) < QUARANTINE_AGE_SEC:
            return False
    except Exception:
        return False
    bad = reqpath + ".bad"
    try:
        if os.path.exists(bad):
            os.remove(bad)
        os.rename(reqpath, bad)
        return True
    except Exception:
        return False


def read_manual_control():
    """读会话接管标志(session_control.json 的 manual_control); 文件缺失/坏 JSON 视为未接管.

    TTL 逃生阀(F8): updated_at 距今超过 MANUAL_CONTROL_TTL_SEC 的标志视为过期(未接管)并
    打印告警; 缺 updated_at 的旧格式永不过期(人类属主, 禁按 pid 存活自动失效)。
    """
    control = read_json_file(SESSION_CONTROL_PATH)
    if not isinstance(control, dict):
        return False
    if not control.get("manual_control"):
        return False
    updated_at = control.get("updated_at")
    if updated_at is not None:
        try:
            age = time.time() - float(updated_at)
        except (TypeError, ValueError):
            age = None
        if age is not None and age > MANUAL_CONTROL_TTL_SEC:
            try:
                print("[worker] manual_control 标志已过期(%.1fh > 24h), 视为未接管" % (age / 3600.0))
            except Exception:
                pass
            return False
    return True


def check_idle_shutdown(last_req_ts):
    """空闲自关判定 (not-files 分支与 processed==0 的 else 分支共用); 返回 (should_exit, new_last_req_ts).

    - IDLE_TIMEOUT_SEC <= 0 = 常驻永不自关(人机共用一个窗口场景, 用例 s4 钉死)。
    - 接管期间冻结空闲计时(返回刷新后的基准): 接管时 agent 请求全被挡, 无请求是常态,
      自关等于把窗口从操作员手里关掉。
    - 刻意不在循环顶调用: 上提会引入"刚落位的合法请求还没处理先被判空闲退出"的竞态,
      只在本轮确认无请求可处理的两个分支里调用 (F7)。
    """
    if IDLE_TIMEOUT_SEC > 0 and time.time() - last_req_ts > IDLE_TIMEOUT_SEC:
        if read_manual_control():
            return (False, time.time())   # 接管冻结: 刷新基准
        return (True, last_req_ts)
    return (False, last_req_ts)


def open_project_with_retry():
    """打开工程; 撞瞬态失败时短退避重试, 平滑"空闲实例正在关闭、新实例抢开"的交叠窗口.

    功能:
        worker 空闲超时会关闭 InoProShop 释放工程锁; 若紧接着有新请求拉起新 worker,
        新实例 projects.open 可能撞上旧实例尚未完全释放的锁(几秒窗口). 此处重试吸收该窗口.
    返回:
        打开的 project 对象
    失败:
        重试耗尽后如实抛出最后一次异常(真实失败如工程被 GUI 手动占用会持续报错并暴露)
    """
    last_exc = None
    for _ in range(5):
        try:
            return projects.open(PROJECT_PATH, u"", True)  # SP11: (path, password, primary); 必须 UI 在场
        except Exception as exc:
            last_exc = exc
            time.sleep(1.0)  # 旧实例释放锁通常在 1~2s 内完成
    raise last_exc


def main():
    ensure_dirs()
    reject_abandoned_deploy_claims()
    write_status("opening")
    try:
        project = open_project_with_retry()
    except Exception as exc:
        write_status("error", {"error": unicode(repr(exc)), "trace": unicode(traceback.format_exc())})
        return
    write_status("ready")

    last_req_ts = time.time()  # 空闲计时基准: 每真正处理一条请求刷新
    fail_counts = {}           # F6: reqpath -> 连续读取失败轮数(读成功/文件消失/隔离时清除)
    responded = set()          # 双 dispatch 防护: 已写响应但请求文件删除失败的 reqpath
    while True:
        if os.path.exists(STOP_PATH):
            if not stop_guard_allows():
                # Direct/old stop sentinels must never terminate a guarded deploy
                # or restore transaction.  Remove the poison pill and keep serving.
                try:
                    os.remove(STOP_PATH)
                except Exception:
                    pass
            else:
                try:
                    os.remove(STOP_PATH)
                except Exception:
                    pass
                break
        try:
            files = sorted([f for f in os.listdir(REQ_DIR) if f.endswith(REQ_SUFFIX)])
        except Exception:
            files = []
        # F6/双 dispatch: 计数与防重集只对仍在目录里的文件有意义, 消失的条目一并清除
        if fail_counts or responded:
            current = set(os.path.join(REQ_DIR, f) for f in files)
            for k in list(fail_counts.keys()):
                if k not in current:
                    fail_counts.pop(k, None)
            responded.intersection_update(current)
        if not files:
            # 空闲超时自关: 关 InoProShop 释放工程独占锁(idle=0 常驻/接管冻结语义见 check_idle_shutdown)
            should_exit, last_req_ts = check_idle_shutdown(last_req_ts)
            if should_exit:
                break
            try:
                system.process_messageloop()  # 泵 UI 事件, 防止 IDE 无响应
            except Exception:
                pass
            time.sleep(POLL_SEC)
            continue
        # 接管期 worker 侧兜底拒执行非 status 请求(客户端拦截的双保险, 防不检查标志的旧客户端直捅)
        manual = read_manual_control()
        processed = 0
        for fn in files:
            rid = fn[:-len(REQ_SUFFIX)]
            reqpath = os.path.join(REQ_DIR, fn)
            if reqpath in responded:
                # 双 dispatch 防护: 上轮已写响应但请求文件删除失败(杀软/索引器占句柄),
                # 只重试删除, 绝不重新派发(write/compile 双执行)。
                try:
                    os.remove(reqpath)
                    responded.discard(reqpath)
                except Exception:
                    pass
                continue
            req = read_request(reqpath)
            if req is None:
                # F6: 连续读取失败 >= QUARANTINE_FAIL_THRESHOLD 轮才隔离(单次瞬态共享冲突
                # 不误伤); 年龄门槛在 quarantine_if_stale 内仍为前置。
                n = fail_counts.get(reqpath, 0) + 1
                fail_counts[reqpath] = n
                if n >= QUARANTINE_FAIL_THRESHOLD and quarantine_if_stale(reqpath):
                    fail_counts.pop(reqpath, None)
                    try:
                        # 隔离补写错误响应: 让等待的客户端快速失败而非烧满超时(F6)
                        write_json_atomic(
                            os.path.join(RESP_DIR, rid + ".resp.json"),
                            {"ok": False,
                             "error": "request quarantined: unreadable request file "
                                      "(%d consecutive read failures): %s" % (n, fn)})
                    except Exception:
                        pass
                continue
            fail_counts.pop(reqpath, None)
            is_deploy = req.get("op") == "deploy"
            claimpath = os.path.join(REQ_DIR, rid + CLAIM_SUFFIX)
            removed = True
            if is_deploy:
                # Physical deploy is executed only after a durable atomic claim.
                # If claim fails, login is never reached; a restart never enumerates
                # claimed files as fresh requests.
                try:
                    os.rename(reqpath, claimpath)
                    reqpath = claimpath
                except Exception:
                    resp = {"ok": False,
                            "error": "deploy request atomic claim failed; login blocked"}
                    try:
                        write_json_atomic(os.path.join(RESP_DIR, rid + ".resp.json"), resp)
                    except Exception:
                        pass
                    processed += 1
                    continue
                removed = False
            else:
                try:
                    os.remove(reqpath)
                except Exception:
                    removed = False   # 删除失败不吞事实: 写完响应后记入 responded, 下轮只重试删除
            allowed, guard_error = deploy_guard_allows(req)
            if not allowed:
                resp = {"ok": False, "error": guard_error}
            elif manual and req.get("op") != "status":
                resp = {"ok": False,
                        "error": "PLC session is under manual control; operation '%s' is blocked" % req.get("op")}
            else:
                resp = dispatch(project, req)
            response_written = False
            try:
                write_json_atomic(os.path.join(RESP_DIR, rid + ".resp.json"), resp)
                response_written = True
            except Exception:
                pass
            if is_deploy and response_written:
                try:
                    os.remove(reqpath)
                    removed = True
                except Exception:
                    removed = False
            if not removed and not is_deploy:
                responded.add(reqpath)
            processed += 1
        if processed:
            last_req_ts = time.time()  # 只在真正处理过请求时刷新——坏文件滞留不再冻结空闲自关
        else:
            # 目录非空但全是半写入/坏文件: 防满速空转; 且隔离失效(rename 恒败/未来 mtime)时
            # 空闲自关仍须生效(F7: 2026-07 事故的另一半), 与 not-files 分支共用同一判定。
            should_exit, last_req_ts = check_idle_shutdown(last_req_ts)
            if should_exit:
                break
            time.sleep(POLL_SEC)
        try:
            system.process_messageloop()
        except Exception:
            pass

    write_status("stopped")


main()
try:
    system.exit()
except Exception:
    try:
        sys.exit(0)
    except Exception:
        pass
