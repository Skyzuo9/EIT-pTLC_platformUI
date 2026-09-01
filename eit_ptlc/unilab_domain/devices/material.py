from __future__ import annotations

from typing import TypedDict

from unilabos.registry.decorators import action, device

from eit_ptlc.unilab_domain.devices.base import PlatformUIProxyBase
from eit_ptlc.unilab_domain.transport_runtime import (
    execute_transport_root,
    preflight_transport,
)
from eit_ptlc.unilab_domain.material_lineage import (
    record_collection,
    record_scraping,
    record_spotting,
)
from eit_ptlc.unilab_domain.operation_review import (
    bind_parallel_operation_inputs,
    run_review_root,
    verify_operation_call,
    verify_review_node,
)
from unilabos.registry.placeholder_type import ResourceSlot


class PlatformActionResult(TypedDict):
    action: str
    request_id: str
    command_id: str
    status: str
    accepted: bool
    result_json: str


class TransportPreflightV4Result(TypedDict):
    operation_name: str
    operation_inputs_json: str
    source_site: str
    target_site: str
    required_tool: str
    source_rail_target: int
    target_rail_target: int
    safety_anchor: str
    command_id: str


class TransportPhysicalV4Result(TypedDict):
    resource: ResourceSlot
    target_site: str
    operation_name: str
    command_id: str
    status: str


class SpottingLineageV4Result(TypedDict):
    sample_vial: ResourceSlot
    plate: ResourceSlot
    stage: str


class ScrapingLineageV4Result(TypedDict):
    plate: ResourceSlot
    powder_collector: ResourceSlot
    stage: str


class CollectionLineageV4Result(TypedDict):
    powder_collector: ResourceSlot
    vial: ResourceSlot
    stage: str


class PlatformOperationReviewV1Result(TypedDict):
    operation_name: str
    command_id: str
    run_id: str
    status: str
    result_json: str
    before_path: str
    collector_hole: int
    bottle_hole: int


class ParallelOperationInputsV1Result(TypedDict):
    inputs_json: str


class OperationReviewMarkerV1Result(TypedDict):
    operation_name: str
    node_path: str
    control_kind: str
    status: str


class OperationCallReviewV2Result(TypedDict):
    operation_name: str
    inputs_json: str
    status: str


@device(
    id='material',
    category=['ptlc', 'material', 'platformui-proxy'],
    displayname='material',
    description='PlatformUI material 的原样动作代理；不复制设备业务逻辑。',
    version='4.0.0',
    model={},
    metadata={'platformui_device_id': 'material',
 'platformui_action_namespace': 'material',
 'runtime_authority': 'PlatformUI',
 'shared_runtime_port': 'eit_ptlc.unilab_domain.runtime_port:PtlcRuntimePort',
 'three_d_facade': 'eit_ptlc/three_d/unilab_facade.v1.yaml',
 'three_d_selector': {'node': None, 'manifest_section': 'inventory'}},
)
class MaterialProxy(PlatformUIProxyBase):
    platformui_namespace = 'material'

    @action(action_name='check_availability', displayname='物料-开工前耗材余量预检', description='执行步骤：对调用方点名的每类耗材各跑一次换板决策查询，判定这一轮能不能取到一件可用耗材；任一类取不到就报错止步，全部可取则返回各类的决策概要。 前置与安全：纯读动作，只查上位机物料账本，不读 PLC、不下发任何指令、不驱动任何运动，任何时刻可调用。刻意放在流程最开头（点样之前）——耗材不足若等到备耗材那一步才发现，样品已经点样、展开、准备刮取，中断代价是白费一个样品；在这里拦下时样品还没动，零损失。 完成与异常：账本中该类存在含未用孔的板时视为可用；某类全部板都无未用孔时返回 ERROR 并点名是哪一类，提示去物料页盘点补录。本动作只看账本余量，不核对中转在位传感器，也不预留任何孔位——预留由随后的实际取用完成。 实现核对：runtime/bootstrap.py::_material_check_availability 调用 runtime/material_store.py::MaterialStore.plan_staging。')
    async def check_availability(self, need_collector: bool = False, need_bottle: bool = False, exclude_sample: str = '') -> PlatformActionResult:
        return await self._invoke('material.check_availability', {'need_collector': need_collector, 'need_bottle': need_bottle, 'exclude_sample': exclude_sample})

    @action(action_name='plan_staging', displayname='物料-耗材换板决策 (含中转在位防呆)', description='执行步骤：读物料账本判定该类耗材下一件从哪来——中转板还有未用孔就原地复用（NONE），中转区空就从货架取一块有料的板（PUT_NEW），中转板已耗尽就先把它送回原库位再取新板（SWAP）；再读该中转区的在位传感器与判定结果核对，一致才把决策返回给调用方。 前置与安全：纯读动作，只查账本并读一个输入字节，不下发任何 PLC 指令、不驱动轴或机器人运动、不修改账本。货架侧无可用在位信号，库位有无一律以账本为准；中转侧的核对是硬门，专防账实失同步下的整板撞机。 完成与异常：返回动作码、要取的货架库位、要送回的满板库位、本件要用的孔号与决策前中转板号；账本判定该类全部板无未用孔时返回 ERROR。中转在位与判定不符时同样返回 ERROR 并说明方向——判定要放新板而传感器报有板（账本漏记了上次搬入，硬放会撞），或判定要用中转板而传感器报空（板被人取走而账本还记着）。输入字节读回空值时报错而不当作全零。 实现核对：runtime/bootstrap.py::_material_plan_staging 调用 runtime/material_store.py::MaterialStore.plan_staging，并按 config/material_topology.yaml 声明的中转传感器位与极性折算在位。')
    async def plan_staging(self, kind: str, reserve_for: str = '') -> PlatformActionResult:
        return await self._invoke('material.plan_staging', {'kind': kind, 'reserve_for': reserve_for})

    @action(
        action_name='transport_preflight_v4',
        displayname='pTLC 通用转运 v4·合同解析',
        description='只读解析物料源位、目标位、工具、地轨目标和唯一 PlatformUI 根 operation。',
    )
    async def transport_preflight_v4(
        self,
        resource: ResourceSlot,
        target_device: str,
        target_mount: ResourceSlot,
        target_site: str,
    ) -> TransportPreflightV4Result:
        return preflight_transport(
            resource=resource,
            target_device=target_device,
            target_mount=target_mount,
            target_site=target_site,
        )

    @action(
        action_name='transport_physical_v4',
        displayname='pTLC 通用转运 v4·锁内执行',
        description='恰好一次提交根 operation；由既有 ResourceGate 全程锁定机器人和地轨。',
    )
    async def transport_physical_v4(
        self,
        resource: ResourceSlot,
        operation_name: str,
        operation_inputs_json: str,
        command_id: str,
        target_site: str,
        timeout_s: float = 3600.0,
    ) -> TransportPhysicalV4Result:
        return await execute_transport_root(
            self._runtime,
            resource=resource,
            operation_name=operation_name,
            operation_inputs_json=operation_inputs_json,
            command_id=command_id,
            target_site=target_site,
            timeout_s=timeout_s,
        )

    @action(
        action_name='record_spotting_v4',
        displayname='记录点样物料谱系',
        description='纯数据连接：把输入样品瓶身份与完成点样的同一硅胶板关联。',
        always_free=True,
    )
    async def record_spotting_v4(
        self, sample_vial: ResourceSlot, plate: ResourceSlot
    ) -> SpottingLineageV4Result:
        return record_spotting(sample_vial, plate)

    @action(
        action_name='record_scraping_v4',
        displayname='记录刮取物料谱系',
        description='纯数据连接：把刮下的样品身份从同一硅胶板关联到接粉器。',
        always_free=True,
    )
    async def record_scraping_v4(
        self, plate: ResourceSlot, powder_collector: ResourceSlot
    ) -> ScrapingLineageV4Result:
        return record_scraping(plate, powder_collector)

    @action(
        action_name='record_collection_v4',
        displayname='记录收集物料谱系',
        description='纯数据连接：把接粉器中的样品身份汇入同一收集瓶。',
        always_free=True,
    )
    async def record_collection_v4(
        self, powder_collector: ResourceSlot, vial: ResourceSlot
    ) -> CollectionLineageV4Result:
        return record_collection(powder_collector, vial)

    @action(
        action_name='bind_parallel_operation_inputs_v1',
        displayname='绑定并行段跨段输出',
        description='把 s4/s7 的真实运行输出覆盖进 s9/s10 输入 JSON；纯数据动作。',
        always_free=True,
    )
    async def bind_parallel_operation_inputs_v1(
        self, inputs_json: str = '{}', before_path: str = '', collector_hole: int = 0, bottle_hole: int = 0
    ) -> ParallelOperationInputsV1Result:
        return bind_parallel_operation_inputs(
            inputs_json=inputs_json,
            before_path=before_path,
            collector_hole=collector_hole,
            bottle_hole=bottle_hole,
        )

    @action(
        action_name='review_operation_call_v2',
        displayname='PlatformUI operation 调用合同',
        description='只读展示并校验 operation 名、格式化参数和源 YAML 摘要；不提交 operation。',
        always_free=True,
    )
    async def review_operation_call_v2(
        self, operation_name: str, inputs_json: str, expected_sha256: str
    ) -> OperationCallReviewV2Result:
        return verify_operation_call(
            operation_name=operation_name,
            inputs_json=inputs_json,
            expected_sha256=expected_sha256,
        )

    @action(
        action_name='review_control_node_v1',
        displayname='PlatformUI 控制节点来源校验',
        description='只读校验审阅投影中的条件、循环、HITL、变量和说明节点仍与源 operation 一致。',
        always_free=True,
    )
    async def review_control_node_v1(
        self, operation_name: str, node_path: str, control_kind: str, expected_sha256: str
    ) -> OperationReviewMarkerV1Result:
        return verify_review_node(
            operation_name=operation_name,
            node_path=node_path,
            control_kind=control_kind,
            expected_sha256=expected_sha256,
        )

    @action(
        action_name='run_operation_review_v1',
        displayname='原子执行 PlatformUI 根 operation',
        description='审阅投影唯一启用的物理节点；整段一次提交，条件、HITL 与 ResourceGate 全由 PlatformUI 执行。',
        always_free=True,
    )
    async def run_operation_review_v1(
        self, operation_name: str, inputs_json: str = '{}', timeout_s: float = 3600.0
    ) -> PlatformOperationReviewV1Result:
        return await run_review_root(
            self._runtime,
            operation_name=operation_name,
            inputs_json=inputs_json,
            timeout_s=timeout_s,
        )


__all__ = ['MaterialProxy']
