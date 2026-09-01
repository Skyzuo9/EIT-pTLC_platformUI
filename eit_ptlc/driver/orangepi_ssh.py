"""香橙派 SSH 远程管理驱动
==========================
功能:
    SSH 到香橙派启动/停止液位检测脚本, 并经 MQTT 监听 water_level/status 确认 online.
    迁移自 UI-Upper/core/orangepi_manager.py.

先决条件:
    - 本机已配置 SSH 密钥免密登录香橙派
    - 香橙派上已部署液位检测脚本 (run.sh)
"""

import asyncio
import json
import logging
import time
from pathlib import Path

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

log = logging.getLogger(__name__)

# SSH 默认选项: 超时, 不检查 host key (避免首次连接交互)
_SSH_OPTS = [
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "BatchMode=yes",
]


class OrangePiManager:
    """通过 SSH 远程管理香橙派液位检测服务."""

    def __init__(
        self,
        ssh_user: str = "orangepi",
        ssh_ip: str = "",
        work_dir: str = "Desktop/work",
        script_name: str = "run.sh",
        broker_ip: str = "192.168.0.168",
        broker_port: int = 1883,
        start_timeout: float = 30.0,
        payload_dir: Path | str | None = None,
        stream_port: int = 7070,
        cameras: str = "",
        tl_bl_cm: float = 15.0,
        cap_width: int = 1920,
        cap_height: int = 1080,
        cap_fps: int = 30,
        exposure_time: int = 312,
        awb_temp: int = 4600,
        no_detect: bool = True,
    ):
        self.ssh_user = ssh_user
        self.ssh_ip = ssh_ip
        self.work_dir = work_dir
        self.script_name = script_name
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.start_timeout = start_timeout
        self.payload_dir = Path(payload_dir) if payload_dir else None
        # 抓帧脚本启动参数 (注入 run.sh 的 "$@"; cameras/tl_bl_cm 缺则脚本 argparse 退出)
        self.stream_port = stream_port
        self.cameras = cameras
        self.tl_bl_cm = tl_bl_cm
        self.cap_width = cap_width
        self.cap_height = cap_height
        self.cap_fps = cap_fps
        # 手动曝光/白平衡定值: 自动曝光会让上位机差分检测整块误判 (见 payload _lock_camera_controls)
        self.exposure_time = exposure_time
        self.awb_temp = awb_temp
        self.no_detect = no_detect
        self._ssh_target = f"{ssh_user}@{ssh_ip}" if ssh_ip else ""
        self._pid_file = "wl.pid"
        self._log_file = "wl.log"
        self._started = False
        # pkill -f 匹配真正的 python 工作进程 (run.sh 仅是 bash 壳, 杀壳留孤儿 python → 停不掉)。
        # 首字符放方括号 [w] 是经典自防误杀技巧: 正则 [w]ater 匹配进程 "water...", 但不匹配本 SSH
        # 命令行里的字面量 "[w]ater" (单引号防 glob 展开)。
        self._proc_pattern = "[w]ater_level_8ch_compress_mqtt.py"

    @property
    def ssh_target(self) -> str:
        return self._ssh_target

    def _script_args(self) -> str:
        """拼装抓帧脚本启动参数 (传给 run.sh → 透传给 water_level_8ch_compress_mqtt.py)。

        run.sh 为纯透传 `python3 ... "$@"`, 故必填 --tl_bl_cm/--cameras 必须经此注入,
        否则脚本 argparse 报 "the following arguments are required" 并立即退出。
        """
        args = [
            f"--tl_bl_cm {self.tl_bl_cm}",
            f"--cameras '{self.cameras}'",
            f"--width {self.cap_width}",
            f"--height {self.cap_height}",
            f"--fps {self.cap_fps}",
            f"--exposure {self.exposure_time}",
            f"--awb_temp {self.awb_temp}",
            f"--broker {self.broker_ip}",
            f"--port {self.broker_port}",
            f"--mjpeg_port {self.stream_port}",
            # SSH/nohup 启动必为无显示环境: 跳过 cv2.imshow 否则 imshow 抛 cv2.error 崩溃
            "--headless",
        ]
        if self.no_detect:
            args.append("--no-detect")
        return " ".join(args)

    async def _run_ssh(self, remote_cmd: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """执行 SSH 远程命令, 返回 (returncode, stdout, stderr)."""
        if not self._ssh_target:
            log.error("[OPI] SSH 目标未配置")
            return -1, "", "SSH 目标未配置"
        cmd = ["ssh"] + _SSH_OPTS + [self._ssh_target, remote_cmd]
        log.debug("[OPI] SSH: %s", remote_cmd)
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
        except asyncio.TimeoutError:
            log.warning("[OPI] SSH 命令超时(%ss): %s", timeout, remote_cmd)
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return -1, "", "SSH 超时"
        except Exception as exc:
            log.error("[OPI] SSH 执行失败: %s", exc)
            return -1, "", str(exc)

    async def deploy_payload(self, timeout: float = 120.0) -> dict:
        """把本机 payload_dir 下的载荷脚本 scp 推送到香橙派 work_dir, 并修正脚本 CRLF。

        推送范围: payload_dir 顶层的 *.py 与 run.sh (script_name); 跳过 __pycache__/README.md/备份。
        返回 {"ok": bool, "files": [...], "error": str}。先决条件同启动: SSH 免密 + scp 在 PATH。
        """
        if not self._ssh_target:
            return {"ok": False, "files": [], "error": "SSH 目标未配置"}
        if self.payload_dir is None or not self.payload_dir.is_dir():
            return {"ok": False, "files": [], "error": f"payload_dir 无效: {self.payload_dir}"}
        # 收集顶层载荷文件: 所有 .py + 启动脚本; 排除缓存/文档 (备份文件本就不在受控 payload_dir)
        files = sorted(
            p for p in self.payload_dir.iterdir()
            if p.is_file() and (p.suffix == ".py" or p.name == self.script_name)
            and p.name != "README.md"
        )
        if not files:
            return {"ok": False, "files": [], "error": f"payload_dir 无可推送文件: {self.payload_dir}"}
        log.info("[OPI] 部署载荷: %d 个文件 -> %s:~/%s", len(files), self._ssh_target, self.work_dir)
        # 1) 确保远端目录存在
        rc, _, err = await self._run_ssh(f"mkdir -p ~/{self.work_dir}", timeout=15.0)
        if rc != 0:
            return {"ok": False, "files": [], "error": f"远端建目录失败: {err}"}
        # 2) scp 推送 (一次性多文件); scp 接受与 ssh 相同的 -o 选项
        dest = f"{self._ssh_target}:~/{self.work_dir}/"
        cmd = ["scp"] + _SSH_OPTS + [str(p) for p in files] + [dest]
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                msg = stderr.decode("utf-8", errors="replace").strip()
                log.error("[OPI] scp 推送失败 (rc=%s): %s", proc.returncode, msg)
                return {"ok": False, "files": [], "error": f"scp 失败: {msg}"}
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return {"ok": False, "files": [], "error": f"scp 超时({timeout}s)"}
        except Exception as exc:
            log.error("[OPI] scp 执行失败: %s", exc)
            return {"ok": False, "files": [], "error": str(exc)}
        # 3) 修正启动脚本 CRLF (Windows 检出可能带 \r, 致香橙派 bash 报错)
        await self._run_ssh(
            f"sed -i 's/\\r$//' ~/{self.work_dir}/{self.script_name}", timeout=10.0)
        names = [p.name for p in files]
        log.info("[OPI] 载荷部署完成: %s", ", ".join(names))
        return {"ok": True, "files": names, "error": ""}

    async def check_remote_running(self) -> bool:
        """SSH 检查香橙派上液位检测进程是否存活 (按脚本名 pgrep, 比 pid 文件更准: pid 可能指向已死的
        bash 壳而 python 仍活, 或反之)."""
        rc, out, _ = await self._run_ssh(
            f"pgrep -f '{self._proc_pattern}' >/dev/null 2>&1 && echo YES || echo NO",
            timeout=10.0,
        )
        return "YES" in out

    async def stop_remote(self) -> bool:
        """SSH 到香橙派 kill 已有液位检测进程."""
        if not self._ssh_target:
            log.warning("[OPI] SSH 目标未配置, 跳过远程停止")
            return False
        log.info("[OPI] 正在远程停止液位检测服务...")
        # 杀 pid 文件壳进程及其子进程, 再 pkill -f 脚本名兜底清掉所有(含历史孤儿)实例, 最后 pgrep 复核。
        rc, out, err = await self._run_ssh(
            f'cd ~/{self.work_dir} 2>/dev/null; '
            f'if [ -f {self._pid_file} ]; then PID=$(cat {self._pid_file}); '
            f'  pkill -TERM -P "$PID" 2>/dev/null; kill -TERM "$PID" 2>/dev/null; '
            f'  rm -f {self._pid_file}; fi; '
            f"pkill -TERM -f '{self._proc_pattern}' 2>/dev/null; sleep 1; "
            f"pkill -KILL -f '{self._proc_pattern}' 2>/dev/null; sleep 0.3; "
            f"if pgrep -f '{self._proc_pattern}' >/dev/null 2>&1; then echo STILL_RUNNING; else echo STOPPED; fi",
            timeout=20.0,
        )
        if "STOPPED" in out:
            log.info("[OPI] 远程停止完成 (已清理全部实例)")
            self._started = False
            return True
        log.warning("[OPI] 远程停止后仍有进程残留 (rc=%d): %s %s", rc, out, err)
        return False

    async def start_remote(self) -> bool:
        """SSH 到香橙派启动液位检测脚本 (nohup + disown), 返回是否成功."""
        if not self._ssh_target:
            log.error("[OPI] SSH 目标未配置, 无法远程启动")
            return False
        if await self.check_remote_running():
            log.info("[OPI] 液位检测服务已在运行, 跳过启动")
            return True
        script_args = self._script_args()
        log.info("[OPI] 正在远程启动液位检测服务...")
        log.info("[OPI]   目标: %s:~/%s", self._ssh_target, self.work_dir)
        log.info("[OPI]   Broker: %s:%s", self.broker_ip, self.broker_port)
        log.info("[OPI]   参数: %s", script_args)
        # nohup + </dev/null 脱离 stdin + disown 脱离 SSH session (避免 SIGHUP)
        remote_cmd = (
            f'cd ~/{self.work_dir} && '
            # 启动前 pkill -f 全清残留实例 (含历史杀不掉的孤儿 python), 保证干净单实例, 避免抢相机/端口
            f"pkill -KILL -f '{self._proc_pattern}' 2>/dev/null; sleep 0.5; "
            f'nohup bash {self.script_name} {script_args} < /dev/null > {self._log_file} 2>&1 & '
            f'disown && PID=$! && echo $PID > {self._pid_file} && echo "STARTED PID=$PID" && '
            f'sleep 2 && '
            f'if kill -0 $PID 2>/dev/null; then echo "RUNNING"; tail -5 {self._log_file} 2>/dev/null; '
            f'else echo "DEAD"; cat {self._log_file} 2>/dev/null; fi'
        )
        rc, out, err = await self._run_ssh(remote_cmd, timeout=30.0)
        # 判据优先用脚本自报的 RUNNING/DEAD 标记 (权威), 而非 SSH rc:
        # rc 反映远程 shell 最后一条命令 (tail/cat/disown) 的退出码, 与脚本存活无关,
        # 故 rc=1 也可能伴随 RUNNING (历史误判 502 的根因)。
        if "DEAD" in out:
            log.error("[OPI] 液位检测进程启动后异常退出 (检查参数/相机/依赖):\n%s", out)
            return False
        if "RUNNING" in out:
            log.info("[OPI] 远程启动成功: %s", out.split("\n")[0])
            self._started = True
            return True
        # 无明确存活标记: 回退到 rc 判定 (SSH 连接本身失败/超时)
        if rc != 0:
            log.error("[OPI] SSH 启动失败 (rc=%d): %s %s", rc, out, err)
            return False
        if "STARTED" in out:
            log.info("[OPI] 远程启动成功 (未取到运行标记): %s", out.split("\n")[0])
            self._started = True
            return True
        log.warning("[OPI] 远程启动状态不明确: %s", out)
        return False

    async def wait_for_online(self, timeout: float | None = None) -> bool:
        """等待香橙派 MQTT status=online 消息, 返回是否在超时内上线."""
        if not MQTT_AVAILABLE:
            log.warning("[OPI] paho-mqtt 不可用, 跳过 MQTT online 等待")
            return True
        wait_secs = timeout if timeout is not None else self.start_timeout
        log.info("[OPI] 等待香橙派 MQTT online (超时 %ss)...", wait_secs)
        online_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _on_msg(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                if payload.get("status") == "online":
                    loop.call_soon_threadsafe(online_event.set)
            except Exception:
                pass

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"opi_wait_{int(time.time())}")
        client.on_message = _on_msg
        try:
            client.connect(self.broker_ip, self.broker_port, keepalive=30)
        except Exception as exc:
            log.warning("[OPI] MQTT 连接失败, 无法等待 online: %s", exc)
            return False
        client.subscribe("water_level/status", qos=0)
        client.loop_start()
        try:
            await asyncio.wait_for(online_event.wait(), timeout=wait_secs)
            log.info("[OPI] 香橙派已上线 (MQTT online)")
            return True
        except asyncio.TimeoutError:
            log.warning("[OPI] 等待 MQTT online 超时(%ss), 继续启动", wait_secs)
            return False
        finally:
            client.loop_stop()
            client.disconnect()

    async def start_and_wait(self) -> bool:
        """完整启动流程: SSH 启动 -> 等待 MQTT online; SSH 启动成功即视为成功."""
        ok = await self.start_remote()
        if not ok:
            return False
        online = await self.wait_for_online()
        if not online:
            log.warning("[OPI] 液位检测已启动但未在超时内报告 online")
        return ok
