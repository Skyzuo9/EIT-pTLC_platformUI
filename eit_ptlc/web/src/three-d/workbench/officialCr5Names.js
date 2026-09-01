/**
 * 功能: 官方 CR5 连杆节点的中文名补充表.
 *
 * 官方 CR5 连杆是管线 raw 阶段导入的 STL, 不在 names.csv 里, 中文名在此单独补.
 * 键与 blender_clean.py build_robot_joints 生成的节点名保持一致.
 * 装配台与动作台的指认模式(都要给 raw 模型建 PartIndex)共用本表.
 */
export const OFFICIAL_CR5_NAMES = [
  ['CR5_BASE_FRAME', '机械臂(官方模型)'],
  ['CR5_BASE', '机械臂底座'],
  ...Array.from({ length: 6 }, (_, i) => [`CR5_LINK${i + 1}`, `机械臂J${i + 1}连杆`]),
  ...Array.from({ length: 6 }, (_, i) => [`CR5_J${i + 1}_ROTOR`, `机械臂J${i + 1}关节`]),
  ['TOOL_MOUNT', '机械臂工具安装位'],
]
