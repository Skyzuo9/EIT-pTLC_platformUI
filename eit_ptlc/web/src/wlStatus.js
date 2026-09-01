// 液位 reason → 用户可读状态 (与 waterlevel_detector/service 的 reason 口径对齐)。
// "前沿未进 ROI" 是物理正常等待态, 必须给中文态而非原样打 reason — 旧 UI 打"无信号"造成
// 误解 (2026-07-16 诊断: 用户把正常等待读成检测失效)。该语义现由 no_front 承担。
const REASON_LABELS = {
  frame_dark: '画面过暗',
  no_roi: '未标定 ROI',
  empty_roi: 'ROI 越界',
  ref_window: '采集参考图中',
  // 流入侧湿平台幅值未起来 = 前沿还没进 ROI, 物理正常等待态
  no_front: '前沿未进入',
  // 下游拖尾也过判湿线 → 整条 profile 被抬平 = 整帧照度/曝光突变, 该拍已弃
  roi_saturated: '整区判湿(已拒)',
  // 干区亮度一拍跳变 = 光照真变了; 守卫已跟上新增益, 但本帧参考图仍属旧光照, 不采信
  gain_step: '照度突变(已弃帧)',
}

export function wlReasonLabel(reason) {
  return REASON_LABELS[reason] || (reason ? `无效 (${reason})` : '无信号')
}

// 增益冻结原因 → 中文。三种冻结语义完全不同, 只显示"已冻结"无从归因:
// 前两种是干区将被/已被前沿打湿(保持旧增益是对的), 页面上属正常保护。
const FROZEN_LABELS = {
  front_near_dry_zone: '前沿逼近干区',
  dry_zone_wet: '干区被打湿',
}

export function wlFrozenLabel(reason) {
  return FROZEN_LABELS[reason] || String(reason || '')
}
