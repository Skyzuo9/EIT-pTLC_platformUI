"""
pTLC 上位机启动入口
===================

统一配置驱动入口（--config PATH）：
  - YAML 配置驱动；依据 mode(pltc/collect/stress) 与 ui.enabled 分派
  - 支持 PLC 自动重连 + 暂停队列等待人工确认
  - stress 模式长时间运行验证 >= 2 小时稳定性

使用方式：
  # 终端1：启动 Mock PLC
  python mock/plc_server.py

  # 终端2：配置驱动入口（推荐）
  python main.py --config config.example.yaml
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
# 压低 asyncua 子 logger 级别，避免 subscription 回调刷屏
logging.getLogger("asyncua").setLevel(logging.WARNING)
log = logging.getLogger("main")


# ======================================================================
# 公共：人工确认回调（仅被内部使用）
# ======================================================================

async def _auto_confirm(task) -> bool:
    """压测/终端模式用自动确认：视觉失败时自动继续。"""
    log.info("[Confirm] 自动选择「继续」")
    return True


async def _terminal_confirm(task) -> bool:
    """终端阻塞确认：视觉失败时等待用户键入 y/n。"""
    loop = asyncio.get_running_loop()
    prompt = f"\n[Confirm] 样品 {task.sample_id} 视觉分析失败，继续执行？(y/n): "
    answer = await loop.run_in_executor(None, input, prompt)
    return answer.strip().lower() == "y"


async def _terminal_resume_confirm() -> bool:
    """终端阻塞确认：PLC 重连成功后是否继续队列。"""
    loop = asyncio.get_running_loop()
    prompt = "\n[Resume] PLC 重连成功，是否继续执行剩余样品？(y/n): "
    answer = await loop.run_in_executor(None, input, prompt)
    return answer.strip().lower() == "y"


# ======================================================================
# Batch 4：Web UI（被 run_from_config 内部调用）
# ======================================================================

def run_batch4(
    requests: Optional[list] = None,
    mock_vision: bool = False,
    vision_output_dir: Path = Path("vision_output"),
    host: str = "0.0.0.0",
    port: int = 8080,
    plc_url: str = "opc.tcp://localhost:4840",
    reconnect_wait_timeout: float = 60.0,
    camera: Optional[object] = None,
    log_persistence_enabled: bool = True,
    log_persistence_flush_interval: float = 0.5,
    log_persistence_batch_size: int = 10,
    log_persistence_archive_days: int = 30,
    database_enabled: bool = True,
    database_path: str = "data/tlc_data.sqlite",
    gcode_cfg: Optional[object] = None,
    vision_cfg: Optional[object] = None,
    water_level_enabled: bool = False,
    water_level_broker_ip: str = "",
    water_level_broker_port: int = 1883,
    water_level_stream_port: int = 8080,
    water_level_orangepi_ip: str = "",
    orangepi_manager: Optional[object] = None,
    robot_runtime: Optional[object] = None,
) -> None:
    """启动 Batch 4 Web UI（NiceGUI）。"""
    from core.scheduler import SampleRequest
    from ui.app import run_ui

    if requests is None:
        requests = [
            SampleRequest(
                sample_id=f"S00{i}",
                before_path=Path("before.png"),
                after_path=Path("after.png"),
                action_timeout=15.0,
            )
            for i in range(1, 4)
        ]

    log.info("=" * 55)
    log.info("pTLC Batch 4 - Web UI 演示（NiceGUI）")
    log.info("  样品数量 : %d", len(requests))
    log.info("  视觉模式 : %s", "Mock（跳过真实分析）" if mock_vision else "真实图像分析")
    log.info("  访问地址 : http://%s:%d", host if host != "0.0.0.0" else "<本机IP>", port)
    log.info("=" * 55)

    run_ui(
        requests=requests,
        mock_vision=mock_vision,
        output_dir=vision_output_dir,
        host=host,
        port=port,
        plc_url=plc_url,
        reconnect_wait_timeout=reconnect_wait_timeout,
        camera=camera,
        log_persistence_enabled=log_persistence_enabled,
        log_persistence_flush_interval=log_persistence_flush_interval,
        log_persistence_batch_size=log_persistence_batch_size,
        log_persistence_archive_days=log_persistence_archive_days,
        database_enabled=database_enabled,
        database_path=database_path,
        gcode_cfg=gcode_cfg,
        vision_cfg=vision_cfg,
        water_level_enabled=water_level_enabled,
        water_level_broker_ip=water_level_broker_ip,
        water_level_broker_port=water_level_broker_port,
        water_level_stream_port=water_level_stream_port,
        water_level_orangepi_ip=water_level_orangepi_ip,
        orangepi_manager=orangepi_manager,
        robot_runtime=robot_runtime,
    )


# ======================================================================
# 配置驱动统一入口
# ======================================================================

def run_from_config(cfg_path: Path) -> None:
    """从 YAML 配置文件读取并分派到对应执行模式。"""
    from core.camera_service import CameraService, MockCameraService, DahengCameraService
    from core.config import load_config
    from core.log_persistence import build_default_persistence
    from core.log_store import LogStore
    from core.plc_client import PLCClient
    from core.recipe import RecipeStore, default_recipe
    from core.robot_service import build_robot_runtime
    from core.scheduler import Scheduler, SampleRequest
    robot_runtime = build_robot_runtime(
        cfg.robot,
        base_dir=cfg_path.resolve().parent,
    )
    from core.vision_service import VisionService, build_vision_from_cfg

    cfg = load_config(cfg_path)
    log.info("[Config] 已加载: %s", cfg_path)
    log.info("[Config] mode=%s ui_enabled=%s samples=%d",
             cfg.mode, cfg.ui.enabled, len(cfg.samples))

    # P2-1：终端模式共享的日志持久化启动/停止 helper
    samples_root = Path("data/samples")
    persistence_cfg = cfg.logging.persistence

    async def _start_persistence(log_store: LogStore):
        if not persistence_cfg.enabled:
            return None
        try:
            persistence = build_default_persistence(
                samples_root=samples_root,
                flush_interval=persistence_cfg.flush_interval_sec,
                batch_size=persistence_cfg.batch_size,
                archive_older_than_days=persistence_cfg.archive_older_than_days,
            )
            await persistence.start()
            log_store.attach_persistence(persistence)
            return persistence
        except Exception as e:
            log.error("[Config] LogPersistence 启动失败（降级为纯内存日志）: %s", e)
            return None

    async def _stop_persistence(persistence) -> None:
        if persistence is None:
            return
        try:
            await persistence.stop()
        except Exception as e:
            log.error("[Config] LogPersistence 停止异常: %s", e)

    # 构建 CameraService 实例
    camera: Optional[CameraService] = None
    if cfg.camera.mock:
        camera = MockCameraService(
            test_image=cfg.camera.test_image,
            test_before_image=cfg.camera.test_before_image,
        )
        log.info("[Config] 相机模式: Mock（预置图=%s, before=%s）",
                 cfg.camera.test_image, cfg.camera.test_before_image)
    else:
        camera = DahengCameraService(params=cfg.camera.daheng)
        log.info("[Config] 相机模式: Daheng（实机, IP=%s）", cfg.camera.daheng.get("ip", "N/A"))

    # ---- mode == stress ----
    if cfg.mode == "stress":
        vision = build_vision_from_cfg(cfg.vision)
        log_store = LogStore()
        start = time.monotonic()
        enqueued = 0

        async def _run_stress():
            nonlocal enqueued
            persistence = await _start_persistence(log_store)
            try:
                async with PLCClient(
                    url=cfg.plc.url,
                    reconnect_wait_timeout=cfg.plc.reconnect_wait_timeout,
                ) as plc:
                    scheduler = Scheduler(
                        plc=plc, vision=vision, camera=camera,
                        confirm_callback=_auto_confirm,
                        log_store=log_store,
                        resume_confirm=None,  # 压测模式自动继续
                    )

                    async def producer() -> None:
                        nonlocal enqueued
                        while time.monotonic() - start < cfg.stress.duration_sec:
                            sid = f"ST{enqueued:06d}"
                            enqueued += 1
                            await scheduler.enqueue(SampleRequest(
                                sample_id=sid,
                                before_path=Path("before.png"),
                                after_path=Path("after.png"),
                                action_timeout=cfg.plc.action_timeout,
                            ))
                            await asyncio.sleep(cfg.stress.interval_sec)
                        log.info("[Stress] 生产者退出（达到时长），等待队列清空")

                    async def consumer() -> None:
                        while time.monotonic() - start < cfg.stress.duration_sec or scheduler.qsize() > 0:
                            await scheduler.run_until_empty()
                            if time.monotonic() - start < cfg.stress.duration_sec:
                                await asyncio.sleep(0.05)

                    await asyncio.gather(producer(), consumer())
            finally:
                await _stop_persistence(persistence)

            # 压测摘要
            entries = log_store.get_all()
            done = sum(1 for e in entries if e.event == "DONE")
            errors = sum(1 for e in entries if e.event == "ERROR")
            elapsed = time.monotonic() - start
            success_rate = (done / enqueued * 100.0) if enqueued else 0.0
            print()
            print("=" * 55)
            print("  压测摘要")
            print("=" * 55)
            print(f"  运行时长       : {elapsed:.1f}s ({elapsed/3600:.2f}h)")
            print(f"  入队样品总数   : {enqueued}")
            print(f"  完成(DONE)     : {done}")
            print(f"  错误(ERROR)    : {errors}")
            print(f"  成功率         : {success_rate:.2f}%")
            print("=" * 55)

        try:
            asyncio.run(_run_stress())
        except ConnectionError as e:
            log.error("PLC连接失败: %s", e)
            log.error("请先在另一个终端启动: python mock/plc_server.py")
            sys.exit(1)
        except Exception as e:
            log.error("运行失败: %s", e)
            sys.exit(1)
        return

    # ---- mode == collect ----
    if cfg.mode == "collect":
        store = RecipeStore(cfg.recipes_dir)
        try:
            recipe_tpl = store.load("collect_only")
        except FileNotFoundError:
            log.warning("[Collect] recipes/collect_only.yaml 不存在，降级用 default_recipe()")
            recipe_tpl = default_recipe()

        vision = build_vision_from_cfg(cfg.vision)
        log_store = LogStore()

        requests = [
            SampleRequest(
                sample_id=f"COLLECT-{i}",
                before_path=Path("before.png"),
                after_path=Path("after.png"),
                action_timeout=cfg.plc.action_timeout,
                recipe=recipe_tpl,
            )
            for i in range(1, cfg.collect_count + 1)
        ]

        async def _run_collect():
            persistence = await _start_persistence(log_store)
            try:
                async with PLCClient(
                    url=cfg.plc.url,
                    reconnect_wait_timeout=cfg.plc.reconnect_wait_timeout,
                ) as plc:
                    from core.consumable_manager import ConsumableManager
                    from core.sample_store import SampleStore
                    # CLI 模式：纯内存 ConsumableManager（persistence_path=None），
                    # 不碰 data/consumable_state.json。SampleStore 共用 data/samples 路径
                    # 供 UI 后续查看，但 CLI 与 UI 不能同时跑。
                    cm = ConsumableManager(persistence_path=None)
                    sample_store = SampleStore(root_dir=Path("data/samples"))
                    scheduler = Scheduler(
                        plc=plc, vision=vision,
                        confirm_callback=_terminal_confirm,
                        log_store=log_store,
                        resume_confirm=_terminal_resume_confirm,
                        sample_store=sample_store,
                        consumable_manager=cm,
                    )
                    for req in requests:
                        await scheduler.enqueue(req)
                    log.info("[Collect] 队列已就绪，开始执行...")
                    await scheduler.run_until_empty()
            finally:
                await _stop_persistence(persistence)
            log_store.print_summary()

        try:
            asyncio.run(_run_collect())
        except ConnectionError as e:
            log.error("PLC连接失败: %s", e)
            log.error("请先在另一个终端启动: python mock/plc_server.py")
            sys.exit(1)
        except Exception as e:
            log.error("运行失败: %s", e)
            sys.exit(1)
        return

    # ---- mode == pltc ----
    if not cfg.samples and not cfg.ui.enabled:
        log.error("[Config] mode=pltc 需要至少一个 samples 条目（或启用 UI 手动入队）")
        sys.exit(1)

    # Batch 6 Phase C：解析 recipe 名称为 RecipeTemplate
    store = RecipeStore(cfg.recipes_dir)

    def _resolve_recipe(name: Optional[str]):
        if not name:
            return None
        try:
            return store.load(name)
        except FileNotFoundError:
            log.warning(
                "[Config] recipe '%s' 不存在于 %s，降级用 default_recipe()",
                name, cfg.recipes_dir,
            )
            return default_recipe()

    requests = []
    for s in cfg.samples:
        recipe_name = s.recipe or cfg.default_recipe
        recipe_tpl = _resolve_recipe(recipe_name)
        if recipe_tpl is not None:
            log.info("[Config] 样品 %s 使用 recipe '%s'", s.id, recipe_tpl.name)
        requests.append(SampleRequest(
            sample_id=s.id,
            before_path=s.before,
            after_path=s.after,
            action_timeout=s.action_timeout if s.action_timeout is not None
                           else cfg.plc.action_timeout,
            recipe=recipe_tpl,
        ))

    # ── 液位检测：SSH 远程启动香橙派脚本（在 UI 之前执行）──
    orangepi_mgr = None
    if cfg.water_level.enabled and cfg.water_level.auto_start:
        from core.orangepi_manager import OrangePiManager
        ssh_ip = cfg.water_level.ssh_ip or cfg.water_level.orangepi_ip
        orangepi_mgr = OrangePiManager(
            ssh_user=cfg.water_level.ssh_user,
            ssh_ip=ssh_ip,
            work_dir=cfg.water_level.work_dir,
            script_name=cfg.water_level.script_name,
            broker_ip=cfg.water_level.broker_ip,
            broker_port=cfg.water_level.broker_port,
            start_timeout=cfg.water_level.start_timeout,
        )

        async def _start_orangepi():
            ok = await orangepi_mgr.start_and_wait()
            if ok:
                log.info("[Config] 香橙派液位检测服务启动成功")
            else:
                log.warning("[Config] 香橙派液位检测服务启动失败，继续主程序")

        try:
            asyncio.run(_start_orangepi())
        except Exception as e:
            log.warning("[Config] 香橙派 SSH 启动异常（继续主程序）: %s", e)

    if cfg.ui.enabled:
        run_batch4(
            requests=requests,
            mock_vision=cfg.vision.mock,
            vision_output_dir=cfg.vision.output_dir,
            host=cfg.ui.host,
            port=cfg.ui.port,
            plc_url=cfg.plc.url,
            reconnect_wait_timeout=cfg.plc.reconnect_wait_timeout,
            camera=camera,
            log_persistence_enabled=persistence_cfg.enabled,
            log_persistence_flush_interval=persistence_cfg.flush_interval_sec,
            log_persistence_batch_size=persistence_cfg.batch_size,
            log_persistence_archive_days=persistence_cfg.archive_older_than_days,
            database_enabled=cfg.database.enabled,
            database_path=cfg.database.path,
            gcode_cfg=cfg.gcode,
            vision_cfg=cfg.vision,
            water_level_enabled=cfg.water_level.enabled,
            water_level_broker_ip=cfg.water_level.broker_ip,
            water_level_broker_port=cfg.water_level.broker_port,
            water_level_stream_port=cfg.water_level.stream_port,
            water_level_orangepi_ip=cfg.water_level.orangepi_ip,
            orangepi_manager=orangepi_mgr,
        )
    else:
        # 无 UI → 终端模式
        vision = build_vision_from_cfg(cfg.vision)
        log_store = LogStore()

        async def _run_pltc_terminal():
            persistence = await _start_persistence(log_store)
            try:
                async with PLCClient(
                    url=cfg.plc.url,
                    reconnect_wait_timeout=cfg.plc.reconnect_wait_timeout,
                ) as plc:
                    from core.consumable_manager import ConsumableManager
                    from core.sample_store import SampleStore
                    # 终端模式：纯内存 ConsumableManager，不碰 data/consumable_state.json。
                    # SampleStore 共用 data/samples，供 UI 后续查看；UI 与本模式不能同时跑。
                    cm = ConsumableManager(persistence_path=None)
                    sample_store = SampleStore(root_dir=Path("data/samples"))
                    scheduler = Scheduler(
                        plc=plc, vision=vision, camera=camera,
                        confirm_callback=_terminal_confirm,
                        log_store=log_store,
                        resume_confirm=_terminal_resume_confirm,
                        sample_store=sample_store,
                        consumable_manager=cm,
                    )
                    for req in requests:
                        await scheduler.enqueue(req)
                    log.info("[Main] 队列已就绪，开始执行...")
                    await scheduler.run_until_empty()
            finally:
                await _stop_persistence(persistence)
            log_store.print_summary()

        try:
            asyncio.run(_run_pltc_terminal())
        except ConnectionError as e:
            log.error("PLC连接失败: %s", e)
            log.error("请先在另一个终端启动: python mock/plc_server.py")
            sys.exit(1)
        except Exception as e:
            log.error("运行失败: %s", e)
            sys.exit(1)


# ======================================================================
# 命令行入口
# ======================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pTLC 上位机")
    parser.add_argument(
        "--config", type=Path, required=True,
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Web UI 监听端口（默认 8080，被 YAML ui.port 覆盖）",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("vision_output"),
        help="视觉分析输出目录（被 YAML vision.output_dir 覆盖）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_from_config(args.config)
