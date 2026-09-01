# -*- coding: utf-8 -*-
"""
功能:
    独立 --runscript 真实下发并自动启动: 把 20260622.project 全下载到真机 PLC, 与 worker_body.op_deploy
    完全同序列 — set_comm_path_by_ip(按 IP 单播设活动路径) -> build(0 错误才继续) ->
    create_online_application -> login(强制全下载, PLC 进 STOP) -> start(自动启动, PLC 运行新程序)
    -> logout. 引导/断电保活由设备「下载创建默认应用」在全下载时自动建(不脚本显式写). 每步结果写
    deploy_runscript_result.json (UI 模式 print 进不了 stdout, 故一律靠结果文件判定).

警告:
    本脚本会 login + 全下载到真机并**自动启动运行** — 不可逆外向操作, 下载完真机立即运动.
    务必在: 真机上电/网络可达 + 机器处于安全、可立即运行态 下运行.

前置:
    工程未被其它 InoProShop 占用 (先停后端 worker / 关其它 IDE).

运行:
    InoProShop.exe --profile="InoProShop(V1.9.1.6)" --runscript=<本文件>
    跑完读: deploy_runscript_result.json
"""
import os
import json
import codecs
import time
import traceback

PROJECT_PATH = r"E:\pTLC_platformUI\eit_ptlc\plc\20260622.project"
RESULT_PATH = r"E:\pTLC_platformUI\eit_ptlc\tools\codesys-mcp\deploy_runscript_result.json"
COMPILE_CATEGORY = "97f48d64-a2a3-4856-b640-75c046e37ea9"
FORCE_FULL_CANDIDATES = ("Never", "ForceDownload", "Force", "FullDownload")  # spike 已确认 Never 存在
PLC_IP = "192.168.0.50"  # 实机 PLC IP(与 app.yaml plc.url 同一台); 用单播定向设活动路径, 绕开广播扫描


def write_result(obj):
    """把结果原子写出(UTF-8).

    用 ensure_ascii=False: 避开 CODESYS 自带 json 的 py_encode_basestring_ascii(它对某些
    中文 unicode 串会触发 ascii 编解码崩溃), 改走非 ascii 转义路径并保留中文; 兜底退 repr。
    """
    try:
        data = json.dumps(obj, ensure_ascii=False)
    except Exception:
        try:
            data = json.dumps(obj)  # 退 ascii 转义路径
        except Exception:
            data = unicode(repr(obj))  # noqa: F821 (CODESYS Py2)
    tmp = RESULT_PATH + ".tmp"
    f = codecs.open(tmp, "w", "utf-8")
    f.write(data if isinstance(data, unicode) else unicode(data))  # noqa: F821 (CODESYS Py2)
    f.close()
    if os.path.exists(RESULT_PATH):
        try:
            os.remove(RESULT_PATH)
        except Exception:
            pass
    os.rename(tmp, RESULT_PATH)


def find_app(project):
    """定位可下发的 Application(优先 active_application, 退回递归 find)."""
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


def resolve_force_full_option():
    """探测 OnlineChangeOption 强制全下载枚举值(规避在线改/全下载 GUI 弹窗); 返回 (value, name)."""
    try:
        enum = OnlineChangeOption  # noqa: F821 (CODESYS 脚本全局)
    except NameError:
        return (None, None)
    for cand in FORCE_FULL_CANDIDATES:
        try:
            return (getattr(enum, cand), cand)
        except Exception:
            continue
    return (None, None)


def build_and_collect_errors(app):
    """编译并收集错误(下发前置门控); 返回 errors 列表 [{severity,text}]."""
    try:
        system.clear_messages(COMPILE_CATEGORY)  # noqa: F821
    except Exception:
        pass
    app.build()
    errors = []
    try:
        msgs = list(system.get_message_objects(COMPILE_CATEGORY))  # noqa: F821
    except Exception:
        msgs = []
    for m in msgs:
        try:
            sev = unicode(getattr(m, "severity", u""))  # noqa: F821
        except Exception:
            sev = u""
        if "error" in sev.lower():
            try:
                txt = unicode(getattr(m, "text", u""))  # noqa: F821
            except Exception:
                txt = u""
            errors.append({"severity": sev, "text": txt})
    return errors


def safe_dir(o):
    """列出对象公开成员名(失败返回空), 供探测 SP11 实际 API 表面."""
    try:
        return sorted([n for n in dir(o) if not n.startswith("_")])
    except Exception:
        return []


def get_gateway():
    """取网关对象: online.gateways['Gateway-1'](用户工程网关名); 退路遍历/索引 0."""
    try:
        gws = online.gateways  # noqa: F821
    except Exception:
        return None
    try:
        g = gws["Gateway-1"]  # dict-like by name
        if g is not None:
            return g
    except Exception:
        pass
    try:
        for g in gws:  # 可迭代
            return g
    except Exception:
        pass
    try:
        return gws[0]
    except Exception:
        return None


def find_device(project):
    """定位要下发的设备节点(有 set_gateway_and_address / get_gateway 的对象)."""
    try:
        hits = list(project.find("Device", True))
        for h in hits:
            if hasattr(h, "set_gateway_and_address") or hasattr(h, "get_gateway"):
                return h
        if hits:
            return hits[0]
    except Exception:
        pass
    try:
        for obj in project.get_children(True):  # 退路: 首个有 get_gateway 的对象
            if hasattr(obj, "set_gateway_and_address") or hasattr(obj, "get_gateway"):
                return obj
    except Exception:
        pass
    return None


def main():
    result = {"project": PROJECT_PATH, "opened": False, "app_found": False,
              "error_count": None, "login_option": None, "steps": [], "fatal": None,
              "deployed": False, "boot_written": False, "started": False}

    def step(name, fn):
        """执行一步, 记录 ok/异常 trace; 抛错不中断后续(各步独立记录, 保证 logout 总能跑)."""
        rec = {"name": name, "ok": False}
        try:
            out = fn()
            rec["ok"] = True
            if out is not None:
                rec["info"] = unicode(out)  # noqa: F821
        except Exception as exc:
            rec["error"] = unicode(repr(exc))  # noqa: F821
            rec["trace"] = unicode(traceback.format_exc())  # noqa: F821
        result["steps"].append(rec)
        return rec["ok"]

    # ---- 打开工程 ----
    try:
        project = projects.open(PROJECT_PATH, u"", True)  # noqa: F821  SP11: (path, password, primary)
        result["opened"] = True
    except Exception as exc:
        result["fatal"] = {"error": unicode(repr(exc)), "trace": unicode(traceback.format_exc())}  # noqa: F821
        write_result(result)
        _exit()
        return

    app = find_app(project)
    result["app_found"] = app is not None
    if app is None:
        result["fatal"] = {"error": u"工程内未找到可下发的 Application"}
        write_result(result)
        _exit()
        return

    # ---- build 门控: 有错即中止, 不进 login ----
    errors = build_and_collect_errors(app)
    result["error_count"] = len(errors)
    if errors:
        result["errors"] = errors
        result["steps"].append({"name": "build_gate", "ok": False, "info": u"编译有错, 已中止下发"})
        write_result(result)
        _exit()
        return

    # ---- 解析强制全下载枚举 ----
    opt, opt_name = resolve_force_full_option()
    result["login_option"] = opt_name
    if opt is None:
        result["fatal"] = {"error": u"未找到强制全下载选项(OnlineChangeOption)"}
        write_result(result)
        _exit()
        return

    # ---- 按 IP 设活动通信路径 (find_address_by_ip 单播定向, 绕开广播扫描) ----
    gw = get_gateway()
    device = find_device(project)
    result["probe"] = {
        "plc_ip": PLC_IP,
        "gateway_found": gw is not None,
        "device_found": device is not None,
        "gateway_dir": safe_dir(gw),
        "device_dir": safe_dir(device),
    }
    if device is not None:
        try:
            result["probe"]["device_current_gateway"] = unicode(device.get_gateway())  # noqa: F821
        except Exception as exc:
            result["probe"]["device_current_gateway"] = u"ERR: " + unicode(repr(exc))  # noqa: F821
        try:
            result["probe"]["device_current_address"] = unicode(device.get_address())  # noqa: F821
        except Exception as exc:
            result["probe"]["device_current_address"] = u"ERR: " + unicode(repr(exc))  # noqa: F821

    def set_path():
        if gw is None:
            raise RuntimeError(u"未取到网关对象(online.gateways)")
        if device is None:
            raise RuntimeError(u"未取到设备对象(project.find Device)")
        # 优先: find_address_by_ip(单播定向) + set_gateway_and_address(设活动路径)
        if hasattr(gw, "find_address_by_ip") and hasattr(device, "set_gateway_and_address"):
            addr = gw.find_address_by_ip(PLC_IP)
            device.set_gateway_and_address(gw, addr)
            return u"set_gateway_and_address(find_address_by_ip=%s) 完成: %s" % (PLC_IP, unicode(addr))  # noqa: F821
        # 退路: 扫描后按名设(若上面方法名不符, 见 probe.gateway_dir/device_dir 真名)
        if hasattr(gw, "perform_network_scan"):
            gw.perform_network_scan()
        raise RuntimeError(u"find_address_by_ip/set_gateway_and_address 不可用, 见 probe.*_dir 真实方法名")

    step("set_communication_path", set_path)  # 失败也继续: login 会暴露, 且 probe 已留真值表

    # ---- 危险序列: login 全下载 -> 写引导 -> logout (不 start) ----
    oa = [None]

    def mk_handle():
        # 论坛示例 create_online_application 无参(用工程活动 application); 带 app 参数疑为
        # create_boot_application 空引用根源, 故无参优先, 失败退带参
        try:
            oa[0] = online.create_online_application()  # noqa: F821
            if oa[0] is not None:
                return u"online_application 句柄已创建(无参)"
        except Exception:
            oa[0] = None
        oa[0] = online.create_online_application(app)  # noqa: F821  退路: 带 app 参数
        return u"online_application 句柄已创建(带 app 参数)"

    if not step("create_online_application", mk_handle):
        write_result(result)
        _exit()
        return

    def do_login():
        oa[0].login(opt, True)  # 强制全下载: PLC 进入 STOP(不走在线改, 规避 GUI 弹窗)
        return u"login + 全下载 完成"

    if step("login", do_login):
        result["deployed"] = True  # login 成功即真机已被改写(STOP)

        def settle():
            # 全下载后泵消息循环 + 短歇, 让在线状态落定(规避 create_boot_application 空引用)
            for _ in range(20):
                try:
                    system.process_messageloop()  # noqa: F821
                except Exception:
                    pass
                time.sleep(0.1)
            return u"settle(2s 消息循环)完成"

        step("settle_after_login", settle)

        # 自动启动: login 全下载本身即自动启动; start 若报"已在运行"即视作成功(引导由设备「下载创建默认应用」自动建)
        def do_start():
            try:
                oa[0].start()
                return u"start 完成"
            except Exception as exc:
                if "is run" in unicode(repr(exc)).lower():  # noqa: F821
                    return u"已在运行(全下载已自动启动)"
                raise
        if step("start", do_start):
            result["started"] = True
        step("logout", lambda: (oa[0].logout(), u"logout 完成")[1])

    write_result(result)
    _exit()


def _exit():
    try:
        system.exit()  # noqa: F821  UI 模式不会自动结束, 必须显式退出
    except Exception:
        pass


main()
