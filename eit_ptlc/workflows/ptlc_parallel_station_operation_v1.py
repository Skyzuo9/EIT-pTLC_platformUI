# AUTO-GENERATED FILE. DO NOT EDIT.
# Source DAG: eit_ptlc/config/recipes/parallel_v1.yaml
# Exporter: tools/export_unilab_workflow_variants.py
# UniLab-only material/transport projection template for parallel_v1.
from __future__ import annotations

from typing import TypedDict

from unilabos.registry.placeholder_type import ResourceSlot
from unilabos.workflow.authoring import (
    MaterialFlowRole,
    device,
    group,
    material_source,
    parallel,
    resource_ref,
    workflow,
)

from eit_ptlc.unilab_domain.devices.material import MaterialProxy
from eit_ptlc.unilab_domain.devices.plc_collect import PLCCollect
from eit_ptlc.unilab_domain.devices.plc_develop import PLCDevelop
from eit_ptlc.unilab_domain.devices.plc_photoscrape import PLCPhotoScrape
from eit_ptlc.unilab_domain.devices.plc_sampling import PLCSampling
from eit_ptlc.unilab_domain.devices.plc_staginga import PLCStagingA
from eit_ptlc.unilab_domain.resources.materials import (
    collection_vial,
    powder_collector,
    ptlc_plate,
    source_sample_vial,
)
from eit_ptlc.workflows.transport_resource_v4 import transport_resource_v4


class PTLCParallelV4Result(TypedDict):
    sample: ResourceSlot
    waste_plate: ResourceSlot
    powder_collector: ResourceSlot


sampling: PLCSampling = device("plc_sampling")
develop: PLCDevelop = device("plc_develop")
photoscrape: PLCPhotoScrape = device("plc_photoscrape")
collect: PLCCollect = device("plc_collect")
staging: PLCStagingA = device("plc_staginga")
material: MaterialProxy = device("material")


@workflow(
    workflow_uuid="c76bb7fd-add3-58b7-b950-bdf494c9af80",
    displayname="pTLC 最长全流程 · 统一 run_station_operation Action 版",
    description=(
        "所有工位 operation 都通过统一 run_station_operation_v4 Action 提交；"
        "机器人、地轨、工具与物料转移仍只进入通用转运 v4。依赖图保持"
        "parallel_v1：s2∥s3、(s6→s8)∥s7，且 s7 的共同前驱为 s5。"
    ),
)
def ptlc_parallel_station_operation_v1(
    *,
    sample_id: str = "DEMO-001",
    sampling_prepare_inputs_json: str = "{}",
    sampling_execute_inputs_json: str = '{"plate_spec":"4×6","plate_no":"1","well":"A1"}',
    develop_prepare_inputs_json: str = '{"tank":1}',
    develop_wait_inputs_json: str = '{"tank":1,"auto_drain":true,"dry_duration_s":0.0}',
    before_photo_inputs_json: str = '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo"}',
    photoscrape_inputs_json: str = '{"sample_id":"DEMO-001","save_dir":"var/photoscrape/demo","before_path":"var/photoscrape/demo/before.jpg","mode":"auto"}',
    collect_execute_inputs_json: str = '{"solvent_volume_ml":0.1,"liquid_repeat_count":1}',
    tank_site: str = "tank-1",
    collector_site: str = "collector-item-1",
    bottle_site: str = "bottle-item-1",
) -> PTLCParallelV4Result:
    """Run one sample while preserving PlatformUI's physical and lock authority."""

    # Typed material inputs.  The source sample stays at the sampling rack;
    # plate and consumables preserve identity through every transport return.
    # unilab:node_uuid=3f201522-2ed4-553d-8d07-4556654b54c9
    sample_vial = material_source(
        resource_template=source_sample_vial,
        mode="existing",
        mount=resource_ref("plc_sampling"),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.PRIMARY_SAMPLE,
    )
    # unilab:node_uuid=a6902393-1b0e-5abc-9b12-01d0df178327
    plate = material_source(
        resource_template=ptlc_plate,
        mode="existing",
        mount=resource_ref("plc_feedlift"),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.ALIQUOT_SAMPLE,
    )
    # unilab:node_uuid=d7567e4f-dd84-5021-8f9b-b361535cf1e1
    collector_input = material_source(
        resource_template=powder_collector,
        mode="existing",
        mount=resource_ref("staging_a_stack"),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.CONSUMABLE,
    )
    # unilab:node_uuid=df5df7d8-a3a5-5d42-903d-ad3c6759abae
    vial_input = material_source(
        resource_template=collection_vial,
        mode="existing",
        mount=resource_ref("staging_b_stack"),
        material_uuid=None,
        site=None,
        slot_range=None,
        flow_role=MaterialFlowRole.CONSUMABLE,
    )

    # unilab:node_uuid=3858c302-fe05-5b8c-83f2-65e144010e03
    with group(name="af0 开工预检"):
        # unilab:node_uuid=11a6ed31-0cd8-5482-8376-025868220cac
        availability = material.check_availability(  # noqa: F841
            need_collector=True,
            need_bottle=True,
            exclude_sample=sample_id,
        )

    # unilab:node_uuid=6152679b-9d19-5c7d-9c33-9ad9d400d090
    with group(name="s1 上样上料"):
        # Exact PlatformUI station preparation; its root has no robot/rail.
        # unilab:node_uuid=18a6946d-8d20-57a1-a863-eca0f3551a5c
        sampling_ready = sampling.run_station_operation_v4(  # noqa: F841
            operation_name="sampling_prepare",
            inputs_json=sampling_prepare_inputs_json,
        )
        # unilab:node_uuid=cca4faaf-770d-5fd2-8d25-4d7cd3be8733
        plate_at_spot = transport_resource_v4(
            resource=plate,
            target_device="plc_sampling",
            target_mount=resource_ref("plc_sampling"),
            target_site="plate",
        )

    # parallel_v1 first fork: branch A is s2 then s4; branch B is s3.
    with parallel():
        # unilab:node_uuid=91297aa4-97f8-523e-b62e-398ac169819f
        with group(name="s2 点样 → s4 展开前拍照"):
            # unilab:node_uuid=c07aa5c4-d890-5ad5-86aa-e0bb56aef80a
            spotting = sampling.run_station_operation_v4(  # noqa: F841
                operation_name="sampling_execute",
                inputs_json=sampling_execute_inputs_json,
            )
            # unilab:node_uuid=fa506167-aafb-510e-ae34-015ce167468c
            sampled = material.record_spotting_v4(
                sample_vial=sample_vial,
                plate=plate_at_spot.resource,
            )
            # s4 begins only after s2 in this branch.
            # unilab:node_uuid=cebffe18-dbeb-504c-b205-c5c5c29588d8
            plate_before_photo = transport_resource_v4(
                resource=sampled.plate,
                target_device="plc_photoscrape",
                target_mount=resource_ref("plc_photoscrape"),
                target_site="plate",
            )
            # unilab:node_uuid=f7e0144a-edd9-5b10-aad9-0c8c469b403b
            before_photo = photoscrape.run_station_operation_v4(  # noqa: F841
                operation_name="photoscrape_before_photo_capture",
                inputs_json=before_photo_inputs_json,
            )

        # unilab:node_uuid=2150042f-9923-5993-9d7f-e8665b3d0682
        with group(name="s3 展缸预备"):
            # unilab:node_uuid=5a64b90c-1ee1-5abe-8c83-d7d6bcc2927d
            tank_ready = develop.run_station_operation_v4(  # noqa: F841
                operation_name="develop_prepare",
                inputs_json=develop_prepare_inputs_json,
            )

    # Join(s4, s3) -> s5.  The call below cannot start until both branches end.
    # unilab:node_uuid=6608ee69-7640-5902-81b9-ec6488d0fc70
    with group(name="s5 取板进缸"):
        # unilab:node_uuid=8294d37f-c3a9-52b0-aa2a-49e13c29012f
        plate_in_tank = transport_resource_v4(
            resource=plate_before_photo.resource,
            target_device="plc_develop",
            target_mount=resource_ref("plc_develop"),
            target_site=tank_site,
        )

    # parallel_v1 second fork.  Both branches start after s5.  In particular,
    # s7 cannot place the collector before the pre-development photo in s4.
    with parallel():
        # unilab:node_uuid=4592ea9d-90a6-5e5c-be08-b910f963f381
        with group(name="s6 展开等待 → s8 出缸上刮板台"):
            # unilab:node_uuid=2a425dc3-7d98-5931-849f-140a421ab7bd
            developed = develop.run_station_operation_v4(  # noqa: F841
                operation_name="pf_s6_develop_wait",
                inputs_json=develop_wait_inputs_json,
            )
            # s8 depends only on s6 within this branch, just like parallel_v1.
            # unilab:node_uuid=f4c473f6-7e30-568c-8ba1-d6b5bbd648c8
            plate_at_scrape = transport_resource_v4(
                resource=plate_in_tank.resource,
                target_device="plc_photoscrape",
                target_mount=resource_ref("plc_photoscrape"),
                target_site="plate",
            )

        # unilab:node_uuid=a2a20791-1581-52fb-bd5b-08dca18f052e
        with group(name="s7 备耗材（s5 后）"):
            # These pure planning calls preserve PlatformUI's inventory rules.
            # unilab:node_uuid=cb57c239-6da0-5c6e-bf5f-59379e07b157
            collector_plan = material.plan_staging(  # noqa: F841
                kind="collector", reserve_for=sample_id
            )
            # unilab:node_uuid=733ec278-cba7-5e43-98bc-3ac40f1535bf
            bottle_plan = material.plan_staging(  # noqa: F841
                kind="bottle", reserve_for=sample_id
            )
            # unilab:node_uuid=64c4e189-bd74-5f74-8a3d-5a86d2efa7d7
            locator_a = staging.locator_a(target=True)  # noqa: F841
            # unilab:node_uuid=6b3379db-e3e4-5d9d-8ea2-dcbeb78e228e
            locator_b = staging.locator_b(target=True)  # noqa: F841
            # unilab:node_uuid=7e1cc67e-f8f0-5a87-87b9-78e2e36e870a
            collector_at_scrape = transport_resource_v4(
                resource=collector_input,
                target_device="plc_photoscrape",
                target_mount=resource_ref("plc_photoscrape"),
                target_site="collector",
            )

    # Join(s8, s7) -> s9: plate and collector are both ready.
    # unilab:node_uuid=d9b5bdc5-a368-51c3-a725-bb8bf0144f94
    with group(name="s9 拍照刮取"):
        # unilab:node_uuid=7b1c0c34-817c-51e4-b27e-69b3de149199
        scraped = photoscrape.run_station_operation_v4(  # noqa: F841
            operation_name="photoscrape_process",
            inputs_json=photoscrape_inputs_json,
        )

    # unilab:node_uuid=8d38230b-1e02-5ea1-902a-7848f636c6a8
    with group(name="s10 粉末收集"):
        # Independent material transfers are released together.  PlatformUI's
        # unchanged root locks serialize only their shared robot/rail windows.
        with parallel():
            # unilab:node_uuid=5882badc-7a98-5e03-8a8e-1b3b960a6f62
            with group(name="接粉器入收集站"):
                # unilab:node_uuid=5ff37632-0ea0-50f9-a467-3e33b82afb4a
                collector_at_collect = transport_resource_v4(
                    resource=collector_at_scrape.resource,
                    target_device="plc_collect",
                    target_mount=resource_ref("plc_collect"),
                    target_site="collector",
                )
            # unilab:node_uuid=1a5c9dac-fe28-543c-8f50-e816eb85abbe
            with group(name="收集瓶入收集站"):
                # unilab:node_uuid=63c414e8-97ac-5d80-92c2-ab18e3180453
                vial_at_collect = transport_resource_v4(
                    resource=vial_input,
                    target_device="plc_collect",
                    target_mount=resource_ref("plc_collect"),
                    target_site="vial",
                )
        # unilab:node_uuid=1d53821f-17cb-5a5d-a8e3-9b94ca5d3188
        collection = collect.run_station_operation_v4(  # noqa: F841
            operation_name="collect_execute",
            inputs_json=collect_execute_inputs_json,
        )
        # unilab:node_uuid=00778e78-3848-5547-a5b9-a54b23d7fb57
        lineage = material.record_collection_v4(
            powder_collector=collector_at_collect.resource,
            vial=vial_at_collect.resource,
        )
        with parallel():
            # unilab:node_uuid=31a8637b-e6d1-5d91-9af4-6e2b880a67fa
            with group(name="接粉器回中转 A"):
                # unilab:node_uuid=ebbcf0fc-4a47-5bd4-acf1-b3ed10dc340c
                collector_returned = transport_resource_v4(
                    resource=lineage.powder_collector,
                    target_device="plc_staginga",
                    target_mount=resource_ref("staging_a_stack"),
                    target_site=collector_site,
                )
            # unilab:node_uuid=60c5031f-55da-5860-a243-0fbf4ce41407
            with group(name="收集瓶回中转 B"):
                # unilab:node_uuid=9f6360b2-4a33-59df-974b-91775609e983
                vial_returned = transport_resource_v4(
                    resource=lineage.vial,
                    target_device="plc_staginga",
                    target_mount=resource_ref("staging_b_stack"),
                    target_site=bottle_site,
                )
        with parallel():
            # unilab:node_uuid=90ca8617-eaba-59ad-aac6-5fab787ff549
            with group(name="释放中转 A"):
                # unilab:node_uuid=dc31c5be-d91f-5aa6-8c34-6f041bcf9e56
                locator_a_released = staging.locator_a(target=False)  # noqa: F841
            # unilab:node_uuid=789cfdb1-4258-5222-a355-c018b122260f
            with group(name="释放中转 B"):
                # unilab:node_uuid=6c28aa08-5048-5e4c-bc40-581ddb3f94ef
                locator_b_released = staging.locator_b(target=False)  # noqa: F841

    # unilab:node_uuid=31162ae6-bf57-5a23-81b9-aa60651e2f0d
    with group(name="s11 废板下料"):
        # unilab:node_uuid=9e41770e-25a1-519e-a5d2-bdb21ce78e2a
        waste = transport_resource_v4(
            resource=plate_at_scrape.resource,
            target_device="plc_feedlift",
            target_mount=resource_ref("plc_feedlift"),
            target_site="waste-stack",
        )

    return {
        "sample": vial_returned.resource,
        "waste_plate": waste.resource,
        "powder_collector": collector_returned.resource,
    }
