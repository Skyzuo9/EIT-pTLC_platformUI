/**
 * 机械臂末端工具的权威四态 (driver/robot_transport.py::MountedTool 的前端映射).
 *
 * 机器人没有"挂了哪把刀"的 DI, 权威工具态由状态文件持久化(config/robot_tool_state.json),
 * 靠人工声明改写(robot.set_mounted_tool)。二维 RobotJogPanel 与三维实时页的状态页签
 * 共用这一份, 防两处各抄一遍后漂移。
 */
export const TOOL_NAMES = { 0: '无 (裸腕)', 1: '吸盘 (slot1)', 2: '大夹持 (slot2)', 3: '小夹持 (slot3)' }

export const TOOL_OPTIONS = [
  { id: 0, text: '无' },
  { id: 1, text: '吸盘' },
  { id: 2, text: '大夹持' },
  { id: 3, text: '小夹持' },
]
