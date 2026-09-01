from __future__ import annotations

from typing import TypedDict

from unilabos.registry.decorators import action, device

from eit_ptlc.unilab_domain.devices.base import PlatformUIProxyBase


class PlatformActionResult(TypedDict):
    action: str
    request_id: str
    command_id: str
    status: str
    accepted: bool
    result_json: str


@device(
    id='vision',
    category=['ptlc', 'vision', 'platformui-proxy'],
    displayname='vision',
    description='PlatformUI vision 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={'$ref': 'ptlc_shared_scene',
 'selector': {'kind': 'gltf_subtree',
              'node_index': 1434,
              'node_path': 'ST_VISION',
              'root_transform': 'reset_translation',
              'exclude_node_paths': []}},
    metadata={'platformui_device_id': 'vision',
 'platformui_action_namespace': 'vision',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': 'ST_VISION', 'manifest_section': None}},
)
class VisionProxy(PlatformUIProxyBase):
    platformui_namespace = 'vision'

    @action(action_name='capture_plate_offset', displayname='视觉-读取放板纠偏', description='执行步骤：启用真机视觉时，上位机串行取得视觉锁，按配置经机器人DO点亮补光并等待稳定后触发拍照读取dx、dy、drz，finally关闭补光；识别路径由pallas_vision.local_vision_enabled路由——true走本地OpenCV检测加真机标定线性换算（当前默认），false回落PALLASVision TCP/Bridge；识别失败两条路径统一返回err=111、valid=false哨兵而不抛硬故障，交由流程内人工分支重拍或中止；apply_rz=false时把drz归零。配置disabled或mock时直接返回中性零偏移，不触发补光或相机。 前置与安全：仅用于上料区取板后、点样位放板前；真机模式下视觉服务和机器人IO必须在线，偏移经过XY/角度范围校验，本动作不移动机器人。 完成与异常：合法或中性偏移返回DONE供move_to_point叠加；超限、协议/服务失败返回ERROR；若finally关灯失败也返回ERROR并要求人工确认灯状态，不能声称已经关闭。 实现核对：eit_ptlc/controller/pallas_vision_client.py::capture_plate_offset/_run_with_light，路由与本地算法见 eit_ptlc/tools/pallas_bridge.py::capture 与 eit_ptlc/controller/local_plate_vision.py::measure_offset，经 ActionExecutor._exec_vision 派发。')
    async def capture_plate_offset(self, apply_rz: bool = False) -> PlatformActionResult:
        return await self._invoke('vision.capture_plate_offset', {'apply_rz': apply_rz})


__all__ = ['VisionProxy']
