from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.ros.nodes.presets.host_node import HostNode
from unilabos.workflow.authoring import device, workflow

from eit_ptlc.unilab_domain.devices.material import MaterialProxy


class TransportResourceV4Result(TypedDict):
    resource: ResourceSlot
    target_site: str
    operation_name: str
    command_id: str


material: MaterialProxy = device("material")
host_node: HostNode = device("host_node")


@workflow(
    workflow_uuid="75067f83-c472-51de-8dc5-e99fdc655df6",
    displayname="pTLC 通用转运 v4",
    description=(
        "参数化解析路线，恰好一次提交 PlatformUI 根 operation；既有 ResourceGate "
        "在完整物理过程内同时持有 robot 与 station:rail，成功后才提交同一物料身份。"
    ),
)
def transport_resource_v4(
    *,
    resource: ResourceSlot,
    target_device: str,
    target_mount: ResourceSlot,
    target_site: str,
) -> TransportResourceV4Result:
    """Move one material without exposing rail, robot, locator or tool knobs."""

    # unilab:node_uuid=8edc5ead-dc67-5529-86c6-5fc54428b113
    contract = material.transport_preflight_v4(
        resource=resource,
        target_device=target_device,
        target_mount=target_mount,
        target_site=target_site,
    )
    # This is the only physical call. UNKNOWN is never retried and therefore
    # can never reach the inventory commit below.
    # unilab:node_uuid=50734061-1c3f-5012-a3bc-f6466578f70b
    physical = material.transport_physical_v4(
        resource=resource,
        operation_name=contract.operation_name,
        operation_inputs_json=contract.operation_inputs_json,
        command_id=contract.command_id,
        target_site=contract.target_site,
    )
    # unilab:node_uuid=14656e94-cdfa-5442-887e-44b0e803469c
    committed = host_node.transfer_resource(
        resource=physical.resource,
        target_device=target_device,
        mount_resource=target_mount,
        site=target_site,
    )
    return {
        "resource": committed.resource,
        "target_site": physical.target_site,
        "operation_name": physical.operation_name,
        "command_id": physical.command_id,
    }
