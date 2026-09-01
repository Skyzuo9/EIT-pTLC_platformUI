// 叠加图图例数据 — 色值为**实际渲染色** (Python 端 BGR → CSS RGB 换算)。
// 源: eit_ptlc/controller/vision_quality.py:776-782 (质量叠加, BGR 常量)
//     View/pTLC_Viewing/tlc_analyze.py:33-45 与 controller/vision_controller.py:709-714 (识别标注, BGR)
// 改动 Python 端颜色时须同步此处 (两端无运行时联动, 靠本注释互指)。

export const QUALITY_LEGEND = [
  { color: 'rgb(0,220,0)', shape: 'box', label: '板外接框', note: '质量指标统计 ROI — 整块板, 非 band' },
  { color: 'rgb(220,220,0)', shape: 'box', label: '板旋转四角', note: '旋转角/透视偏斜证据 — 仍是板级' },
  { color: 'rgb(220,0,0)', shape: 'cross', label: '板中心十字', note: '判机械对中' },
  { color: 'rgb(0,220,220)', shape: 'line', label: '四边留白线', note: '板边到画面边的 margin' },
  { color: 'rgb(240,240,240)', shape: 'cross', label: '画面中心/曝光统计', note: '白色十字与文字、直方图' },
]
export const QUALITY_NOTE = '此图只评估拍照质量 (板几何/曝光), 不含 band; 识别结果见识别标注图 (annotated)。'

export const ANNOTATED_LEGEND = [
  { color: 'rgb(255,132,54)', shape: 'box', label: 'band 轮廓', note: '每条检出条带 (代码常量名 CONTOUR_MAGENTA, 实际渲染为橙)' },
  { color: 'rgb(245,245,245)', shape: 'cross', label: 'band 质心', note: '' },
  { color: 'rgb(228,232,232)', shape: 'box', label: '板边界框', note: '' },
]
export const ANNOTATED_NOTE = '此图只表达识别结果，不表达设备将执行的路径；选定 band 后请生成 CNC execution preview。'

export const CNC_LEGEND = [
  { color: 'rgb(255,132,54)', shape: 'box', label: '选中 band 轮廓', note: 'CNC 路径的几何输入' },
  { color: 'rgb(0,216,236)', shape: 'line', label: '铣刀路径', note: '与下发 g_sx/g_sy 同源' },
  { color: 'rgb(180,72,196)', shape: 'line', label: '收集器路径', note: '与下发 g_cx/g_cy 同源' },
  { color: 'rgb(255,255,0)', shape: 'cross', label: '板角X/原点双圈/±轴箭头', note: '程序认定的板坐标系; 原点 cm(0,0) 应贴点样边' },
]
export const CNC_NOTE = '预览由同一次 CNC 数组生成结果反投影；2D 图不表达每 pass 的 Z 切深。'

// 手绘门板坐标系标注 (spec 2026-07-16 §3): 只核标角(相机侧), 不核对刀
export const SKETCH_AXES_LEGEND = [
  { label: '原点 cm(0,0) 双圈', color: '#ffd700', shape: 'cross', note: '程序认定的板原点角 — 应贴点样边' },
  { label: '+x/+y 轴箭头', color: '#ffd700', shape: 'line', note: '板 cm 坐标方向 (经与路径同一映射画出)' },
]
export const SKETCH_AXES_NOTE =
  '标注只验证四角标定/找板(相机侧); 机床对刀偏差在此图不可见 — 用「对位检查」核对。口诀: cm 原点角应贴点样边。'
