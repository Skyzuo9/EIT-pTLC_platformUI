# -*- coding: utf-8 -*-
"""
功能:
    Phase 0 部署能力 spike. 独立 --runscript(不进 worker 主循环, 不走文件 IPC), 在 InoProShop
    (CODESYS SP11) 带 UI 模式下探测并验证 ScriptEngine 的 online / login / download / boot / start
    API 是否真正可用, 把每步结果(成功/异常 trace)与 API 探测信息写到结果文件, 供构建"SP11 可用
    部署调用序列真值表", 据此决定 Phase 2 后端 deploy 如何实现.

为什么不靠 print:
    SP11 UI 模式下脚本 print 进不了 stdout(进了 IDE 消息窗), 故判定一律靠写结果文件.

两阶段(安全门控):
    DO_DOWNLOAD = False (默认): 只做"安全探测" — 打开工程, 创建 online application 句柄,
        dir() 列出 online / online_app / OnlineChangeOption 的成员, 不登录、不下载、不改真机。
        先跑这一步把 API 表面摸清(不碰真机)。
    DO_DOWNLOAD = True: 执行真实的 login + (download/create_boot_application) + start + logout 序列,
        会改写并启动真机 PLC 程序 — 不可逆外向操作。务必在真机处于安全状态、已确认可被打断时才设 True。

前置条件(DO_DOWNLOAD=True 时):
    1. 真机 PLC 已上电、网络可达(能 ping 通)。
    2. 已在 InoProShop GUI 里为设备设好"活动通信路径/网关"(active path) — SP11 脚本设网关未必可行,
       故先 GUI 手动设好, 本脚本只验证 login 之后的链路。

运行:
    "D:\\InoProShop\\CODESYS\\Common\\InoProShop.exe" --profile="InoProShop(V1.9.1.6)" ^
        --runscript="E:\\pTLC_platformUI\\eit_ptlc\\tools\\codesys-mcp\\spike_deploy.py"
    跑完读结果文件: E:\\pTLC_platformUI\\eit_ptlc\\tools\\codesys-mcp\\spike_deploy_result.json
"""
import os
import json
import codecs
import traceback

# ---------- 配置(如仓库路径变动, 改这两行) ----------
PROJECT_PATH = r"E:\pTLC_platformUI\eit_ptlc\plc\20260622.project"
RESULT_PATH = r"E:\pTLC_platformUI\eit_ptlc\tools\codesys-mcp\spike_deploy_result.json"

# ---------- 安全门控: 默认只探测, 不碰真机 ----------
DO_DOWNLOAD = False           # 设 True 才真正 login+download+start 到真机(不可逆!)
FORCE_FULL_DOWNLOAD = True    # login 时尝试"强制全下载"以绕过"在线改/全下载"GUI 弹窗(枚举名见探测结果)


def write_result(obj):
    """把结果以 ASCII-escaped JSON 原子写到 RESULT_PATH(中文转 \\uXXXX, 规避编码坑)."""
    data = json.dumps(obj, indent=2)
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


def safe_dir(obj):
    """列出对象的公开成员名(失败返回空), 供摸清 SP11 实际 API 表面."""
    try:
        return sorted([n for n in dir(obj) if not n.startswith("_")])
    except Exception:
        return []


def find_app(project):
    """定位可编译/可在线的 Application(优先 active_application, 退回递归 find)."""
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


def resolve_login_option():
    """探测 OnlineChangeOption 枚举, 返回 (枚举成员值列表, 选用的 login 选项或 None).

    FORCE_FULL_DOWNLOAD=True 时优先选 Never(强制全下载, 不走在线改, 避免 GUI 弹窗阻塞);
    名称在 SP11 未必叫 Never, 故同时记录全部成员名供人工确认。
    """
    values = []
    chosen = None
    try:
        values = safe_dir(OnlineChangeOption)  # noqa: F821 (CODESYS 脚本全局)
    except Exception:
        values = []
    if FORCE_FULL_DOWNLOAD:
        for cand in ("Never", "ForceDownload", "Force", "FullDownload"):
            try:
                chosen = getattr(OnlineChangeOption, cand)  # noqa: F821
                return values, ("OnlineChangeOption.%s" % cand)
            except Exception:
                continue
    # 未找到强制项 → 返回 None, 由 login 调用方决定是否退回 Try(可能弹窗)
    return values, None


def main():
    result = {
        "project": PROJECT_PATH,
        "do_download": DO_DOWNLOAD,
        "opened": False,
        "app_found": False,
        "probe": {},
        "steps": [],
        "fatal": None,
    }

    def step(name, fn):
        """执行一步, 记录 ok/异常 trace; 抛错不中断后续步骤(各步独立记录)."""
        rec = {"name": name, "ok": False}
        try:
            out = fn()
            rec["ok"] = True
            if out is not None:
                rec["info"] = unicode(out)  # noqa: F821
        except Exception as exc:
            rec["error"] = unicode(repr(exc))      # noqa: F821
            rec["trace"] = unicode(traceback.format_exc())  # noqa: F821
        result["steps"].append(rec)
        return rec["ok"]

    # ---- 打开工程 ----
    try:
        project = projects.open(PROJECT_PATH, u"", True)  # noqa: F821  SP11: (path, password, primary)
        result["opened"] = True
    except Exception as exc:
        result["fatal"] = {"error": unicode(repr(exc)),        # noqa: F821
                           "trace": unicode(traceback.format_exc())}  # noqa: F821
        write_result(result)
        _exit()
        return

    app = find_app(project)
    result["app_found"] = app is not None

    # ---- 安全探测: API 表面(不碰真机) ----
    try:
        result["probe"]["online_dir"] = safe_dir(online)  # noqa: F821
    except Exception:
        result["probe"]["online_dir"] = []

    online_app = [None]  # 闭包可写

    def create_handle():
        online_app[0] = online.create_online_application(app)  # noqa: F821
        return "online_application 句柄已创建"

    if step("create_online_application", create_handle):
        result["probe"]["online_app_dir"] = safe_dir(online_app[0])

    opt_values, opt_name = resolve_login_option()
    result["probe"]["OnlineChangeOption_values"] = opt_values
    result["probe"]["chosen_login_option"] = opt_name

    # ---- 危险序列: 仅 DO_DOWNLOAD=True 才执行真实部署 ----
    if DO_DOWNLOAD and online_app[0] is not None:
        oa = online_app[0]

        def do_login():
            # 优先用探测到的"强制全下载"选项; 否则退回无参/带 bootProject 形式(签名以探测为准)
            if opt_name is not None:
                opt = getattr(OnlineChangeOption, opt_name.split(".")[-1])  # noqa: F821
                oa.login(opt, True)
            else:
                oa.login()
            return "login 完成"

        def do_boot():
            oa.create_boot_application()  # 写引导应用: 断电重启保活(现场必须)
            return "create_boot_application 完成"

        def do_start():
            oa.start()
            return "start 完成"

        def do_logout():
            oa.logout()
            return "logout 完成"

        if step("login", do_login):
            step("create_boot_application", do_boot)
            step("start", do_start)
        step("logout", do_logout)
    else:
        result["steps"].append({
            "name": "deploy_sequence",
            "ok": True,
            "info": u"DO_DOWNLOAD=False, 已跳过真实 login/download/start(仅探测 API)。"
                    u"确认 API 与前置条件后, 设 DO_DOWNLOAD=True 再跑以验证真机部署。",
        })

    write_result(result)
    _exit()


def _exit():
    try:
        system.exit()  # noqa: F821  UI 模式不会自动结束, 必须显式退出
    except Exception:
        pass


main()
