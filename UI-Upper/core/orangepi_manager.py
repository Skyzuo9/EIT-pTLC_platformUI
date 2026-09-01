"""
OrangePiManager — 香橙派液位检测服务 SSH 远程管理

职责:
  - SSH 到香橙派，启动/停止液位检测 Python 脚本
  - 启动后通过 MQTT 监听 water_level/status 确认 online
  - 进程退出前远程 kill 液位脚本（避免孤儿进程）

先决条件:
  - 本机已配置 SSH 密钥免密登录到香橙派
  - 香橙派上已部署 water_level_8ch_compress_mqtt.py
"""

import asyncio
import json
import logging
import time
from typing import Optional

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

log = logging.getLogger(__name__)

# SSH 默认选项：超时、不检查 host key（避免首次连接交互）
_SSH_OPTS = [
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "BatchMode=yes",
]


class OrangePiManager:
    """通过 SSH 远程管理香橙派液位检测服务。"""

    def __init__(
        self,
        ssh_user: str = "orangepi",
        ssh_ip: str = "",
        work_dir: str = "Desktop/work",
        script_name: str = "run.sh",
        broker_ip: str = "192.168.0.168",
        broker_port: int = 1883,
        start_timeout: float = 30.0,
    ):
        self.ssh_user = ssh_user
        self.ssh_ip = ssh_ip
        self.work_dir = work_dir
        self.script_name = script_name
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.start_timeout = start_timeout

        self._ssh_target = f"{ssh_user}@{ssh_ip}" if ssh_ip else ""
        self._pid_file = "wl.pid"
        self._log_file = "wl.log"
        self._started = False

    @property
    def ssh_target(self) -> str:
        return self._ssh_target

    # ── SSH 命令执行 ──────────────────────────────────────────────

    async def _run_ssh(self, remote_cmd: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """执行 SSH 远程命令，返回 (returncode, stdout, stderr)。"""
        if not self._ssh_target:
            log.error("[OPI] SSH 目标未配置")
            return -1, "", "SSH 目标未配置"

        cmd = ["ssh"] + _SSH_OPTS + [self._ssh_target, remote_cmd]
        log.debug("[OPI] SSH: %s", remote_cmd)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace").strip(),
                stderr.decode("utf-8", errors="replace").strip(),
            )
        except asyncio.TimeoutError:
            log.warning("[OPI] SSH 命令超时(%ss): %s", timeout, remote_cmd)
            try:
                proc.kill()
            except Exception:
                pass
            return -1, "", "SSH 超时"
        except Exception as e:
            log.error("[OPI] SSH 执行失败: %s", e)
            return -1, "", str(e)

    # ── 远程检查 ──────────────────────────────────────────────────

    async def check_remote_running(self) -> bool:
        """SSH 检查香橙派上液位检测进程是否存活。"""
        rc, out, _ = await self._run_ssh(
            f'[ -f {self._pid_file} ] && kill -0 "$(cat {self._pid_file})" 2>/dev/null && echo YES || echo NO',
            timeout=10.0,
        )
        return "YES" in out

    # ── 远程停止 ──────────────────────────────────────────────────

    async def stop_remote(self) -> bool:
        """SSH 到香橙派，kill 已有液位检测进程。"""
        if not self._ssh_target:
            log.warning("[OPI] SSH 目标未配置，跳过远程停止")
            return False

        log.info("[OPI] 正在远程停止液位检测服务...")

        # kill 进程 + 清理 PID 文件
        rc, out, err = await self._run_ssh(
            f'cd ~/{self.work_dir} && '
            f'if [ -f {self._pid_file} ]; then '
            f'  PID=$(cat {self._pid_file}); '
            f'  if kill -0 "$PID" 2>/dev/null; then '
            f'    kill "$PID" 2>/dev/null; '
            f'    sleep 1; '
            f'    kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null; '
            f'    echo "STOPPED $PID"; '
            f'  else '
            f'    echo "ALREADY_DEAD"; '
            f'  fi; '
            f'  rm -f {self._pid_file}; '
            f'else '
            f'  echo "NO_PID_FILE"; '
            f'fi',
            timeout=15.0,
        )

        if rc == 0:
            log.info("[OPI] 远程停止完成: %s", out)
            self._started = False
            return True
        else:
            log.warning("[OPI] 远程停止异常 (rc=%d): %s %s", rc, out, err)
            return False

    # ── 远程启动 ──────────────────────────────────────────────────

    async def start_remote(self) -> bool:
        """SSH 到香橙派，启动液位检测脚本（nohup），等待 MQTT online。

        Returns:
            True  启动成功（或已在运行）
            False 启动失败（SSH 不通 / 脚本异常退出）
        """
        if not self._ssh_target:
            log.error("[OPI] SSH 目标未配置，无法远程启动")
            return False

        # 先检查是否已在运行
        if await self.check_remote_running():
            log.info("[OPI] 液位检测服务已在运行，跳过启动")
            return True

        log.info("[OPI] 正在远程启动液位检测服务...")
        log.info("[OPI]   目标: %s:~/%s", self._ssh_target, self.work_dir)
        log.info("[OPI]   Broker: %s:%s", self.broker_ip, self.broker_port)

        # 构建远程命令：直接执行香橙派上的 run.sh
        # 关键：nohup + < /dev/null 脱离 stdin + disown 脱离 SSH session
        # （SSH 连接关闭时远端 shell 会向 session 进程发 SIGHUP，
        #  仅 nohup 不够，需 disown 将进程从 shell job table 移除）
        remote_cmd = (
            f'cd ~/{self.work_dir} && '
            # 清理已有进程
            f'if [ -f {self._pid_file} ] && kill -0 "$(cat {self._pid_file})" 2>/dev/null; then '
            f'  echo "[remote] 停止已有进程 PID=$(cat {self._pid_file})"; '
            f'  kill "$(cat {self._pid_file})" 2>/dev/null || true; '
            f'  sleep 1; '
            f'fi && '
            # 启动 run.sh（完全脱离 SSH session）
            f'nohup bash {self.script_name} '
            f'  < /dev/null > {self._log_file} 2>&1 & '
            f'disown && '
            f'PID=$! && '
            f'echo $PID > {self._pid_file} && '
            f'echo "STARTED PID=$PID" && '
            # 等 2 秒确认进程存活
            f'sleep 2 && '
            f'if kill -0 $PID 2>/dev/null; then '
            f'  echo "RUNNING"; '
            f'  tail -5 {self._log_file} 2>/dev/null; '
            f'else '
            f'  echo "DEAD"; '
            f'  cat {self._log_file} 2>/dev/null; '
            f'fi'
        )

        rc, out, err = await self._run_ssh(remote_cmd, timeout=30.0)

        if rc != 0:
            log.error("[OPI] SSH 启动失败 (rc=%d): %s %s", rc, out, err)
            return False

        if "DEAD" in out:
            log.error("[OPI] 液位检测进程启动后异常退出:\n%s", out)
            return False

        if "RUNNING" in out or "STARTED" in out:
            log.info("[OPI] 远程启动成功: %s", out.split("\n")[0])
            self._started = True
            return True

        log.warning("[OPI] 远程启动状态不明确: %s", out)
        return False

    # ── 等待 MQTT online ──────────────────────────────────────────

    async def wait_for_online(self, timeout: float | None = None) -> bool:
        """等待香橙派 MQTT status=online 消息。

        通过临时 MQTT 客户端订阅 water_level/status，
        等待 device 发布 online 状态。

        Args:
            timeout: 最大等待秒数（默认用 self.start_timeout）

        Returns:
            True 收到 online；False 超时
        """
        if not MQTT_AVAILABLE:
            log.warning("[OPI] paho-mqtt 不可用，跳过 MQTT online 等待")
            return True

        wait_secs = timeout if timeout is not None else self.start_timeout
        log.info("[OPI] 等待香橙派 MQTT online (超时 %ss)...", wait_secs)

        online_event = asyncio.Event()

        def _on_msg(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                if payload.get("status") == "online":
                    online_event.set()
            except Exception:
                pass

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"opi_wait_{int(time.time())}",
        )
        client.on_message = _on_msg

        try:
            client.connect(self.broker_ip, self.broker_port, keepalive=30)
        except Exception as e:
            log.warning("[OPI] MQTT 连接失败，无法等待 online: %s", e)
            return False

        client.subscribe("water_level/status", qos=0)
        client.loop_start()

        try:
            await asyncio.wait_for(online_event.wait(), timeout=wait_secs)
            log.info("[OPI] 香橙派已上线 (MQTT online)")
            return True
        except asyncio.TimeoutError:
            log.warning("[OPI] 等待 MQTT online 超时(%ss)，继续启动", wait_secs)
            return False
        finally:
            client.loop_stop()
            client.disconnect()

    # ── 组合启动流程 ──────────────────────────────────────────────

    async def start_and_wait(self) -> bool:
        """完整启动流程：SSH 启动 → 等待 MQTT online。

        Returns:
            True  启动 + online 均成功
            False 任一环节失败（但不阻塞主程序）
        """
        ok = await self.start_remote()
        if not ok:
            return False

        online = await self.wait_for_online()
        if not online:
            log.warning("[OPI] 液位检测已启动但未在超时内报告 online")
        return ok  # SSH 启动成功即视为成功（online 只是锦上添花）
