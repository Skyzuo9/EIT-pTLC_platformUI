# config/backup — 归档配置

存放**不再被运行期加载**的旧配置文件。保留它们仅为离线工具/历史可追溯, 不属于上位机运行所需配置。

- `robot_flows_v2.yaml` — 机器人路线/模板真源 (v2)。派生点已全部并入 `points/robot/robot_points_meta.json` 的 `supplement`, 运行期不再叠加此文件 (见 bootstrap 注释)。仅:
  - `tools/gen_robot_point_operations.py` 离线从它生成 `config/operation/07_robot/*.yaml`;
  - `operation/robot_routes/*` 未接入运行期的 planner 子系统及其离线测试引用它。

- `operation_retired/` — R2 站 cycle 化后退役的跨站 transfer 流程脚本 (原 `config/operation/02_transfer/`)。这些单体 transfer 内嵌站动作违反 R2 承重墙 (站动作只归各站 `*_cycle`), 已逐一解交错并入对应站 cycle, **零引用、勿调用**。归档于此仅供历史比对; 现役跨站 move 由顶层 recipe (`ptlc_full_v2`) 串机器人转运。退役清单:
  - `transfer_feed_to_spotting` → 并入 `08_feedlift/feedlift_load_cycle` + `03_sampling/sampling_cycle`;
  - `transfer_spotting_to_scrape` / `transfer_scrape_to_tank` / `transfer_tank_to_scrape` → 并入 `06_photoscrape/*` + `04_develop/develop_cycle`;
  - `transfer_scrape_to_waste` → 并入 `06_photoscrape/photoscrape_pick` + `08_feedlift/feedlift_unload_cycle`;
  - `transfer_collector_collect_to_staging_a` / `transfer_collector_scrape_to_collect` → 并入 `05_collect/collect_cycle` (clamp/release_clamp 归 cycle)。
