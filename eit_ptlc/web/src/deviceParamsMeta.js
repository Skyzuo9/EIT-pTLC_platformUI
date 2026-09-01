// 设备参数释义表: 键 = app.yaml 的完整点号路径 (段名 + 段内路径)。
// 段名必须带上: DeviceParamsPanel 的 flatten() 只产出段内路径, camera 与 vision 都有 mock,
// 不带段名会串段贴错中文名 (pump 三工位的 asp_speed/disp_speed/step_delay 靠工位前缀区分, 不冲突)。
//
// desc 三段约定: 单位与量程 \n 物理作用 \n 注意事项 (渲染侧 white-space: pre-line 分行)。
// 单位/量程真源 = config/loader.py 的 _parse_camera/_parse_gcode/_parse_vision/_parse_pump,
// driver/daheng_capture.py 的 UV_WORKING_LIMIT_MS=1800, config/plc_nodes.yaml 的 g_scrape_feed;
// 物理作用一律以消费代码为准而非 app.yaml 注释 (已核出 10 处注释与代码不一致)。
// 两个 flush 键的 UI 文案用「充液润洗」而非内部术语「轻清洗」, 双术语并存是刻意的。
const PARAM_META = {
  // ---- vision: 识别与条带检测 (5 个识别参数每次 analyze 实时读盘, mock/output_dir 烘定需重启) ----
  'vision.mock': {
    label: '视觉模拟',
    desc: '布尔.\ntrue 时跳过真实图像分析, 直接返回固定模拟条带, 仅供无图像环境联调.\n生产必须 false, 否则拿到的条带是假的. 启动时烘定, 改后需重启上位机.',
  },
  'vision.output_dir': {
    label: '分析输出目录',
    desc: '字符串, 相对上位机进程工作目录 (不是 config 目录).\n视觉产物 (summary.json / 标注图 / after_normalized.jpg) 的根目录, 同时是 /api/vision/image 的图片服务根与调试台"载入生产 case"的扫描根.\n越出该目录的写盘会被 422 拒绝. 启动时烘定, 改后需重启.',
  },
  'vision.image_plate_orientation': {
    label: '板图朝向',
    desc: '枚举 rot0 | rot90cw | rot180 | rot270cw.\n对原始相机帧做无损 90 度整数旋转, 使"图像下沿 = 物理板点样线边"这一下游假设成立; 现役 rot0 即点样线在图像底部.\ndetect_origin_band 只在归一化帧高度 45%~96% 区间搜原点带, 选错朝向会直接找不到原点带. 与手绘画布及 gcode.origin_corner 同帧, 三者必须一起改.',
  },
  'vision.auto_rectify_tilt': {
    label: '自动纠倾',
    desc: '布尔.\n仅当固定滚转角为空时, true 才逐帧用绿板 minAreaRect 估倾角并 warpAffine 矫正; 已给固定角时它降级为交叉校验, 只在实测角与固定角相差超过 1.0 度时打 WARN, 不改变实际旋转量.\n现役固定角路径下建议保持 true, 以便相机被碰后及时发现.',
  },
  'vision.rectify_min_angle_deg': {
    label: '纠倾死区角',
    desc: '单位: 度, 须 >= 0.\n倾角绝对值小于本值就不旋转, 避免为零点几度噪声白挨一次重采样插值; 对固定角与自动估两条路径同时生效.\n现役固定角 -2.43 度大于 0.5, 所以矫正确实在做.',
  },
  'vision.min_row_score': {
    label: '行评分阈值',
    desc: '无量纲差分评分 (与差分强度同尺度), 须 >= 0.\n行剖面峰值达到本值才算候选条带行; 条带上下肩边界用 max(本值 x 0.75, 峰值 x 0.30), 溶剂前沿用 max(本值 x 0.75, 4.0).\n图高 >= 800 且正值行超过 20 时实际阈值被抬到 max(本值, 正值行 P70), 此时本值只是下限. 调低多检出但易把噪点当带, 调高会漏掉弱带.',
  },
  'vision.image_plate_rotation_deg': {
    label: '固定滚转角',
    desc: '单位: 度, 量程 [-180, 180]; 置空 (null) 才回落逐帧自动估.\n相机滚转角标定值, 主路径 deskew 直接按它旋转 (板与相机固定, 倾角是常量, 不必每帧现估).\n现役 -2.43 是真机实测标定值, 非经重新标定不要改. 置空且自动纠倾也是 false 则完全不纠倾.',
  },

  // ---- camera: 大恒 GigE 相机采集 (全部启动时烘定, 改后必须重启上位机) ----
  'camera.mock': {
    label: '相机模拟',
    desc: '布尔.\ntrue 时用预置图替代真机拍照, 完全忽略 daheng.* 全部参数.\nsim 模式会强制置 true 以防误触真机 UV; 生产必须 false. 启动时烘定, 改后需重启.',
  },
  'camera.test_image': {
    label: '模拟后照片',
    desc: '字符串, 相对进程工作目录.\n相机模拟为 true 时作为 after.jpg 来源的预置图.\n仅模拟模式生效, 实机模式该键完全无作用.',
  },
  'camera.test_before_image': {
    label: '模拟前照片',
    desc: '字符串, 相对进程工作目录.\n相机模拟为 true 时 before.jpg 的来源; 存在时拍 after.jpg 会顺带复制一份 before.jpg, 双帧分析才成立.\n留空或文件不存在则 before 也退回模拟后照片. 仅模拟模式生效.',
  },
  'camera.daheng.ip': {
    label: '相机 IP',
    desc: 'IPv4 字符串.\n大恒 GigE 相机地址; 驱动用 open_device_by_ip 精确打开该台设备, 连不上直接报错而不会随便挑一台.\n须与上位机同网段. 注意本机另有一台 .163 本地视觉相机 (pallas_vision.local_vision_enabled 用), 勿混.',
  },
  'camera.daheng.exposure_time': {
    label: '曝光时间',
    desc: '单位: 微秒 (us), 须 > 0; 实际上下限由相机 ExposureTime 特征 GetRange 决定.\n决定画面亮度, 是调曝光的首选旋钮.\n现役 1000000 us = 1000 ms, 正好等于 UV 点亮时长, 已贴在安全校验边界上: 硬约束是折成 ms 后不得大于 UV 点亮时长, 再增曝光必须同步增大 UV 点亮时长, 否则拍照被直接拒.',
  },
  'camera.daheng.gain': {
    label: '模拟增益',
    desc: '相机 Gain 特征的原生单位值, 须 >= 0; 代码只透传不校验上限 (上限由相机自身决定).\n传感器模拟增益, 提亮比加曝光快.\nUV 荧光成像应优先加曝光而非加增益: 抬增益会同步放大噪声, 影响行评分阈值的可比性.',
  },
  'camera.daheng.pixel_format': {
    label: '像素格式',
    desc: '字符串, 现役 RGB8 (可选项随机型: BGR8 / Mono8 / BayerRG8 等).\n相机输出的像素格式.\n相机不支持时驱动只打 WARNING 并沿用当前格式, 不报错; 且落盘前一律转成 RGB8, 所以改它主要影响传输量而非最终图像通道数.',
  },
  'camera.daheng.trigger_mode': {
    label: '触发模式',
    desc: '枚举 On (软触发) | Off (连续采集).\nOn = 按需拍单帧, Off = 连续采集取最新帧.\nUV 自动控光为 true 时必须是 On, 否则拍照被直接拒绝 —— 连续采集会取到开灯前的旧帧或暗帧. 现役 UV 安全路径固定 On, 且相机不支持 On 时驱动直接失败而不回退 Off.',
  },
  'camera.daheng.trigger_source': {
    label: '触发源',
    desc: '字符串, 现役 Software; 仅触发模式为 On 时有效.\n软触发的触发来源.\nUV 自动控光为 true 时必须是 Software 且相机须实现 TriggerSoftware, 否则拒绝开灯拍照. 外部触发未在本机走通.',
  },
  'camera.daheng.timeout_ms': {
    label: '采图超时',
    desc: '单位: ms.\n触发后等一帧回来的上限, 超时报采图失败.\n必须大于曝光时间的毫秒值. 开 UV 时实际超时会被再钳到"UV 硬截止 2000 ms 减去已点灯时长", 所以设得比 2000 大没有意义, 现役 2000 已到实际天花板.',
  },
  'camera.daheng.width': {
    label: '图像宽度',
    desc: '单位: 像素, 0 = 不修改 (用相机当前值或满幅).\n非 0 时写相机 Width 特征做 ROI 裁剪, 与 ROI X 偏移配对.\n固定滚转角与 gcode 板原点都是按满幅帧标定的, 改 ROI 会让这些标定失效; 裁窄还会把板边裁掉导致找板失败. 无特殊需要就留 0.',
  },
  'camera.daheng.height': {
    label: '图像高度',
    desc: '单位: 像素, 0 = 不修改 (用相机当前值或满幅).\n非 0 时写相机 Height 特征做 ROI 裁剪, 与 ROI Y 偏移配对.\n除与宽度同样的标定失效风险外, 图高 >= 800 会触发行评分阈值的 P70 自适应抬阈分支, 把图缩到 800 以下会实质改变条带检测行为.',
  },
  'camera.daheng.offset_x': {
    label: 'ROI X 偏移',
    desc: '单位: 像素.\nROI 左上角的横向偏移.\n只在 > 0 时才写相机 OffsetX, 即 0 的含义是"不修改"而非"归零": 把已非 0 的偏移在面板改回 0 不会真的清零相机 ROI, 界面值会与实际不符. 图像宽度为 0 (满幅) 时无意义.',
  },
  'camera.daheng.offset_y': {
    label: 'ROI Y 偏移',
    desc: '单位: 像素.\nROI 左上角的纵向偏移.\n同样只在 > 0 时才写入, 0 表示不修改, 无法在面板上归零. 图像高度为 0 (满幅) 时无意义.',
  },
  'camera.daheng.auto_light_control': {
    label: 'UV 自动控光',
    desc: '布尔.\ntrue 时驱动执行原子 UV 序列: 强制关灯 -> 开灯 -> 软触发抓帧 -> 关灯, 并挂请求截止与硬截止两个独立定时器强制关灯.\n置 false 会跳过全部 UV 计时与关灯保护, 光源须外部自负, 会让 UV 持续照射加速样品降解, 生产不要关.',
  },
  'camera.daheng.light_line': {
    label: '光源输出线',
    desc: '字符串, 现役 Line1 (Pin7/8 光耦输出).\n相机上 UV 光源实际接的数字输出引脚; 驱动按 LineSelector -> 本值, LineSource -> UserOutput0, UserOutputValue -> 电平 的链路开关 UV.\n填错引脚等于开灯失败, 拍照会被直接拒绝而不是静默拍黑图. 只有现场改接线口才动它.',
  },
  'camera.daheng.uv_on_time_ms': {
    label: 'UV 点亮时长',
    desc: '单位: ms, 工作上限 1800 (UV_WORKING_LIMIT_MS), 且必须 >= 曝光时间的毫秒值.\nUV 光源单次允许点亮的时长.\n现役 1000 与 1000 ms 曝光正好贴死, 抬曝光前先抬本值. 该校验在拍照时才做, 面板保存不查, 填 1900 会保存成功而在实际拍照时报错. (另有一条不在本面板的 uv_hard_cutoff_ms 硬截止上限 2000 ms, 是两条不同的限值.)',
  },

  // ---- gcode: 板标定 + 刮取/收集工艺, Z 正方向 = 向下 (全部实时读盘, 每次调用重读) ----
  'gcode.origin_corner': {
    label: '板原点角',
    desc: '枚举 lower-left | top-right | top-left | bottom-right (大小写敏感, 只做去空格).\n声明板坐标原点落在归一化图像哪个角, 内部映射成 (flip_x, flip_y) 决定板 cm 增量对应机床 mm 的正负; 现役 lower-left 即两轴都不翻转.\n与 vision.image_plate_orientation 及手绘画布同帧, 三者必须一起改. 改错会让整套路径镜像或翻转, 有撞机风险.',
  },
  'gcode.plate_origin_x': {
    label: '板原点机床 X',
    desc: '单位: mm (机床坐标).\n归一化图像左下角 (板 cm 0,0) 对应的机床 X, 直接整体平移全部刮取与收集路径.\n真机实测标定值 (由旧右上角 291.02 减一个板宽推得), 用对位面板写入, 非重新实测不要手估.',
  },
  'gcode.plate_origin_y': {
    label: '板原点机床 Y',
    desc: '单位: mm (机床坐标).\n板 cm 0,0 即点样线所在底边对应的机床 Y, 同样整体平移路径.\n真机实测 -75.2, 离机械撞机点不足 5 mm, 须与机床 Y 软下限配套; 标定量, 不可随意改.',
  },
  'gcode.plate_surface_z_mm': {
    label: '板面 Z 基准',
    desc: '单位: mm, Z 正方向向下.\n刀尖刚接触硅胶板面的机床 Z, 所有切深以它为零点: 每刀深度 = 本值 + k x 总刮深 / 分刀次数.\n真机对刀标定量; 换刀或换板厚必须重新对刀. 换刀只改本值, 不必动对位抬高余量. 改大 = 刀更深, 过深会铣穿玻璃基板.',
  },
  'gcode.align_clearance_mm': {
    label: '对位抬高余量',
    desc: '单位: mm.\n对位检查高度 = max(0, 板面 Z 基准 - 本值); 因 Z 向下, 相减即抬高. 现役 20.5 - 2.5 = 18.0, 即离板面 2.5 mm 悬空目视对位.\n只影响检查高度, 不影响刮取深度; 它只是余量, 不是第二个刀长真源.',
  },
  'gcode.machine_y_min_mm': {
    label: '机床 Y 软下限',
    desc: '单位: mm (机床坐标); 置空 (null) = 关闭该保护.\n防撞机钳位: 刮取与收集每个 Y 点都钳到不低于本值, 发生钳制时打 WARN.\n现役 -73 是防撞标定值; 代价是贴底 band 底部会被截平导致收粉不全, 不可为多刮一点而下调.',
  },
  'gcode.collector_x_positive': {
    label: '收集器在 +X 侧',
    desc: '布尔, 描述本机硬件安装事实, 不是可调工艺参数.\n收集器 (粉桶) 是否位于铣刀的机床 +X 方向. 与 origin_corner 推出的 flip_x 不一致时 (如现役 rot0/lower-left 加收集器在 +X), 生成器把整条路径的 X 绕 bbox 右端镜像回规范帧 —— 机床位置不变只改遍历序, 使铣刀落在 band 的 -X 侧而收集器正好压住 band.\n与真实安装不符会让拖尾方向反打, 收集全部脱靶.',
  },
  'gcode.path_strategy': {
    label: '路径策略',
    desc: '枚举 zigzag | boustrophedon | contour (自动转小写).\ncontour = 按谱带轮廓逐列采样, 是生产唯一推荐值, 也是刮取列保留比与逐列刀补腐蚀唯一生效的策略; boustrophedon 列内单向列间换向; zigzag 每点一个 180 度 U 形回头, 机械冲击大.\n另两种是早期实验策略, 仅留作回归对照, 生产不要选.',
  },
  'gcode.boustrophedon_columns': {
    label: '列数下限',
    desc: '整数, 必须整除 400 (PLC 点位数组长度), 合法值 1/2/4/5/8/10/16/20/25/40/50/80/100/200/400.\n它不是最终列数而是下限: 实际列数 = max(按铣刀直径 x (1 - 刀路重叠率) 推导的覆盖列数, 本值), 再向上取到最近的 400 因子.\n400 虽能通过保存校验, 但 contour 要求每列至少 2 点会在生成时报错, 实际请不超过 200.',
  },
  'gcode.scrape_keep_ratio': {
    label: '刮取列保留比',
    desc: '无量纲, 区间 (0, 1]; 仅 contour 策略生效.\n每列在轮廓采样出的纵向长度按本比例以列中心为轴收缩, 1 = 整列全刮.\n调小可只取谱带核心以纯度优先, 代价是回收率下降; 其他策略对它无感.',
  },
  'gcode.collect_margin_mm': {
    label: '收集绝对余量',
    desc: '单位: mm (每侧), 须 >= 0.\n收集 Y 半跨度 = 收集乘性包络 x 带半高 + (本值 - 桶口半径), 桶口半径 = 收集桶口直径 / 2; 真实作用是抵掉桶口自身的覆盖宽度, 不重复计入.\n现役 6 扣掉 2.5 后净外扩 +3.5 mm/侧, 用于覆盖恒定的散粉晕. 真机标定值.',
  },
  'gcode.collect_expand_ratio': {
    label: '收集乘性包络',
    desc: '无量纲, 区间 [1.0, 2.0].\n按比例放大收集路径的局部带半高, 随带体量正比增长, 专治硅胶崩飞; 1.0 表示只用绝对余量.\n与收集绝对余量线性叠加不会双计. 调大收得更全, 但更容易带进邻带杂质. 真机标定值.',
  },
  'gcode.tool.cutter_diameter_mm': {
    label: '铣刀直径',
    desc: '单位: mm.\n双重作用: 一是自动列数推导的有效步距 = 本值 x (1 - 刀路重叠率), 二是开刀补时内缩半径 R = 本值 / 2 + 纯度安全边.\n必须与实际装的刀一致: 填大了欠覆盖漏刮, 填小了刀刃会越出谱带轮廓过切.',
  },
  'gcode.tool.cutter_compensation': {
    label: '刀径补偿',
    desc: '布尔.\ntrue 时刮扫中心路径双侧内缩 R = 刀半径 + 纯度安全边, 使刀刃外缘不越出谱带轮廓 (纯度优先); 带宽窄于刀径的列会收拢到区间中点并汇总一条 WARN. 收集路径不受影响.\n默认 false 是零回归, 真机显式开; 关掉后刀刃会啃到邻带污染样品.',
  },
  'gcode.tool.compensation_margin_mm': {
    label: '纯度安全边',
    desc: '单位: mm (单侧), 区间 [0, 10]; 仅刀径补偿为 true 时生效.\n在刀半径之外再多让开这么多, 用于补视觉分割的边界误差.\n现役 0 表示只让刀半径; 调大提纯度, 降回收率.',
  },
  'gcode.tool.bottle_diameter_mm': {
    label: '收集桶口直径',
    desc: '单位: mm.\n粉桶 (收集器) 的开口直径; 桶口半径 = 本值 / 2, 会从收集绝对余量中扣除得到净外扩量.\n换桶必须同步改本值, 否则收集 Y 跨度整体偏移.',
  },
  'gcode.tool.bottle_x_offset_mm': {
    label: '铣刀桶 X 间距',
    desc: '单位: mm.\n铣刀与收集器沿机床 X 的刚性间距, 同时就是收集路径拖尾段长度: 铣刀到 x_max 时收集器还差这一段没吸到, 拖尾段专门补收它.\n现役 90 是真机实测值 (由 85 改来以治 -X 端堆积), 标定量; 填错会让收集路径整体错位收不到粉.',
  },
  'gcode.tool.bottle_y_offset_mm': {
    label: '铣刀桶 Y 偏移',
    desc: '单位: mm, 区间 [-20, 20].\n收集器相对铣刀的 Y 向装配偏移补偿, 只平移收集路径中心, 刮取路径不受影响.\n现役 -3 是真机拨符号后的实测值, 标定量. 注意 app.yaml 该行注释的方向描述已过时: 代码是 y_center += 本值 / 10 再以 flip_y=False (lower-left) 正向映射, 故本值越正机床 Y 越大, 与注释所写相反.',
  },
  'gcode.scrape.total_depth_mm': {
    label: '总刮深',
    desc: '单位: mm, 代码无上下限校验.\n自板面 Z 基准往下的硅胶层累计切深, 按分刀次数均分成每刀深度 (Z 正向下).\n现役 1 mm 一刀切透一层硅胶; 超过硅胶层实际厚度会切到玻璃基板.',
  },
  'gcode.scrape.bulk_factor': {
    label: '粉末松散系数',
    desc: '无量纲倍数, 区间 [0.5, 5.0].\n刮下来的硅胶粉相对板上压实涂层的体积膨胀倍数; 物料账本按「谱带轮廓面积 x 总刮深 x 本值」估算进桶粉量并落库, 三维据此画粉柱高度.\n只影响记账与显示, 不进任何路径/切深/PLC 计算 —— 改它绝不会改变刮取动作. 现役 1.6 是按硅胶层压实密度与松散堆积密度之比取的估值, 未实测标定; 标定办法是量一次已知面积与切深的刮取粉实际体积反算.',
  },
  'gcode.scrape.num_passes': {
    label: '分刀次数',
    desc: '整数, 小于 1 会被抬成 1, 无上限校验.\n把总刮深分成几层递进下刀, 上位机 VM 逐 pass 写 g_pass_z; 现役 1 即一刀切透总刮深.\n增大可减小单刀切削力与硅胶崩飞, 代价是节拍近似线性翻倍 —— 一次刮取触发同跑刮扫段+收集段, 而收集段约占单刀行程 89%, 每刀都会整条重跑一遍 (实测标定图案 1 刀 5.3min / 3 刀 15.9min), 不是只有切削部分变长.\n首次调大务必先小尺寸 dry-run: 现役一直是 1, N>1 真机未跑过, 且整条路径跑在同一个 g_pass_z 上, 第 2 刀起刀前刀具是否抬起未经验证 — 若看到刀在切深上横穿板面立即停机.',
  },
  'gcode.scrape.overlap_ratio': {
    label: '刀路重叠率',
    desc: '无量纲比例, 实际可用区间 [0, 1), 代码不校验.\n有效步距 = 铣刀直径 x (1 - 本值), 步距再决定自动列数以保证横向覆盖无遗漏; 现役 0.4 即相邻刀路重叠 40%.\n调大更保覆盖但列数上升节拍变长; 填到 1 以上会让步距归零并退化成 1 列.',
  },
  'gcode.scrape.feed_rate': {
    label: '刮扫进给',
    desc: '单位: mm/min, 整数; 下发的 PLC 节点 g_scrape_feed 是 Int16, 故实际不超过 32767.\n刮扫插补的合成进给速度.\n现役 800 是真机整定值. 太快硅胶崩飞或伺服失步, 太慢单板耗时明显变长; 改动后应先小尺寸低进给 dry-run 核对方向与覆盖再提速.',
  },
  'gcode.collection.return_sweep': {
    label: '收集回走',
    desc: '布尔.\ntrue = 拖尾正向补收 (x_max - 铣刀桶 X 间距 到 x_max) 之后, 再从 x_max 一路 -X 扫回 x_min 收残粉 (全面收集); false = 只走拖尾段, 即旧行为.\n回走全程 -X 保证桶壁只朝板内推粉, 不会把粉从开口边推出界. 关掉省时, 代价是回收率下降.',
  },

  // ---- pump: 注射泵档默认 (实时读盘, 改后下次派发即生效; 删除某键 = 回退代码常量) ----
  // 优先级 = 运行前动作/流程参数 > 本段 > translator 常量兜底。速度是下发 SY-03B 的原始 V 值,
  // 本面板不换算 (只有动作/流程 knob 才带 scale 0.25 转 mL/min 的显示皮肤); 240 半步 = 1 mL,
  // 全程 25 mL / 6000 步, 故 1 档 = 0.25 mL/min。
  'pump.sampling.asp_speed': {
    label: '上样吸液速度',
    desc: '单位: 半步/s, 量程 1..500; 现值 250 约 62.5 mL/min.\n上样泵每一个吸液子动作的速率: 1 口吸清洗溶剂, 3 口吸样品/空气/回收液, 4 口吸驱动空气, 以及回抽泄压, 也包含吹打混匀的吸入半程.\n缺省值, 未被动作/流程参数覆盖时才生效; 现役 sampling_execute 固定传 50, 故本值实际只在单动作调试时露面. 太快会把气泡一起吸进针管.',
  },
  'pump.sampling.disp_speed': {
    label: '上样打液速度',
    desc: '单位: 半步/s, 量程 1..500; 现值 100 = 25 mL/min.\n名字比实际管辖范围大: 只管重清洗的推出与吹打混匀的排出, 不管点样也不管充液润洗.\n想改点样流量请调点样打液速度, 想改润洗请调充液润洗打速或点样头润洗打速, 改本键对那三者毫无影响. 缺省值, 可被动作/流程参数覆盖.',
  },
  'pump.sampling.spot_disp_speed': {
    label: '点样打液速度',
    desc: '单位: 半步/s, 量程 1..500; 现值 9 = 2.25 mL/min, 刻意取极低值以精度优先.\n真正把样品挤到 TLC 板上的送液速率. 走条带点样路径 (sampling.spot_band_layer, PLC A62) 时它与 spot_speed_mm_s 共同决定每毫米条带的样品毫升数, 两者须一起调.\n缺省值; 现役 sampling_execute 自带默认 6 会覆盖本值. 调大点斑会摊开变糊, 直接毁掉分离度.',
  },
  'pump.sampling.step_delay': {
    label: '上样步间延时',
    desc: '单位: ms. app.yaml 与 loader 放行 0..60000, 但动作 YAML knob 只声明 0..10000 且 build_rinse_mix_array 超过 10000 直接抛错, 故可安全使用的范围是 0..10000.\n泵固件在每个柱塞子动作后, 下一次换阀前保持的停顿, 让有弹性的液柱稳定液面再动阀.\n上样管路最长最含气 (针到泵约 16.825 mL), 所以三个工位里它的延时最长. 缺省值, 可被覆盖; 调小提速但容易带气泡或拖液.',
  },
  'pump.sampling.flush_disp_speed': {
    label: '充液润洗打速',
    desc: '单位: 半步/s, 量程 1..500; 现值 300 = 75 mL/min.\n充液润洗中经上样针路径的两段推送: 先充液约 17 mL 从针尖排出, 再洗针外壁约 5 mL 到废液.\n刻意取高值 —— 需要快流冲掉贴管壁的气泡, 气体除净才消掉那份柔度, 吸液后滴液才会停. 缺省值, 可被覆盖; 调低会洗不净.',
  },
  'pump.sampling.spot_head_disp_speed': {
    label: '点样头润洗打速',
    desc: '单位: 半步/s, 量程 1..500; 现值 100 = 25 mL/min.\n充液润洗第三段: 外部三通阀切换后冲洗点样头支路约 3 mL 的推速.\n刻意低于充液润洗打速, 因为该支路细且容积小不能硬加压. 该段固定打到 A0, 结束时柱塞回到 0 位. 缺省值, 可被覆盖; 只影响润洗环节, 不影响点样本身.',
  },
  'pump.sampling.spot_end_position_ml': {
    label: '点样柱塞终点',
    desc: '单位: mL (柱塞绝对位置, 本段唯一浮点键), 量程 0.0..5.0.\n死体积补偿停点: 取 0 时柱塞到底后仍在把纯驱动液推上板, 稀释并拖宽条带尾部; 停在 N 就正好留下这么多驱动液不打出去. 同时写入 Int16 PLC 节点 Sampling_band_end_position, A62 以 spot_band_pos <= N + 5 收尾.\n现役过阀排空编排下 sampling_execute 总用 N = D + G/2 (D = 1.125 mL 三通到针死体积, G = 气隔断, 缺省 1.225) 覆盖本值, 故 app.yaml 这个数仅是单动作调试兜底. 对早于该特性的固件下发 N > 5 会让 A62 空转到 60 遍上限并报 ErrorCode 462.',
  },
  'pump.collect.asp_speed': {
    label: '收集吸液速度',
    desc: '单位: 半步/s, 量程 1..500; 现值 500 = 125 mL/min, 已顶到守卫上限.\n收集泵 (地址 3) 单条复合指令 /3V{asp}I2A{steps}M{delay}V{disp}I1A0M{delay}R 的吸入速率, 从 2 口抽洗脱溶剂.\n直接取上限是因为这是无需计量精度的大体积溶剂输送. 缺省值, 可被覆盖; 太快易吸入气泡.',
  },
  'pump.collect.disp_speed': {
    label: '收集打液速度',
    desc: '单位: 半步/s, 量程 1..500; 现值 500 = 125 mL/min, 已顶到守卫上限.\n同一条复合指令的排出速率, 经 1 口推入收集器; PLC 按 collect_count 重复整条指令.\n同样取上限, 追求节拍不追求精度. 缺省值, 可被覆盖; 太快易溅液.',
  },
  'pump.collect.step_delay': {
    label: '收集步间延时',
    desc: '单位: ms, 安全范围 0..10000 (loader 放行到 60000).\n复合指令中吸, 排两个子动作后各自保持的停顿, 待液面稳定再换阀, 避免对着还在动的液柱切阀.\n缺省值, 可被覆盖; 调小提速但液面未稳就动会带气泡.',
  },
  'pump.develop.asp_speed': {
    label: '展开配液吸速',
    desc: '单位: 半步/s, 量程 1..500; 现值 100 = 25 mL/min.\n展开泵 (地址 1 管缸 1-4, 地址 2 管缸 5-8, T-06 阀) 唯一的那个 V: 柱塞按累积绝对位置依次从 2-5 口吸入最多 4 种流动相配出比例.\n慢是刻意的 —— 这一程行程本身就是比例计量, 速度直接决定配比精度. 缺省值; 现役 develop_prepare 自带 tank_asp_speed 默认 300 会覆盖本值.',
  },
  'pump.develop.disp_speed': {
    label: '展开配液打速',
    desc: '单位: 半步/s, 量程 1..500; 现值 100 = 25 mL/min.\n配好的混合溶剂一次性排入目标展缸的速率 (输出口: 泵 1 用 6 口, 泵 2 用 1 口).\n与吸速独立以便进缸温和. 缺省值; 现役 develop_prepare 自带 tank_disp_speed 默认 300 会覆盖本值. 太快会冲乱缸内液面与溶剂前沿.',
  },
  'pump.develop.step_delay': {
    label: '展开步间延时',
    desc: '单位: ms, 安全范围 0..10000 (loader 放行到 60000).\n每吸完一种溶剂通道后保持的停顿, 稳定液面, 保证阀转到下一路溶剂前液柱已经静止.\n直接关系配比重复性. 缺省值, 可被覆盖; 调小提速但液面未稳就动会影响前沿判读.',
  },
}

// 查段内点号路径的中文名与释义; 未登记返回 null (调用侧据此回落只显示原始 key).
// section 必须带上: 段内路径本身不唯一 (camera 与 vision 都有 mock)。
export function paramMeta(section, path) {
  return PARAM_META[`${section}.${path}`] || null
}
