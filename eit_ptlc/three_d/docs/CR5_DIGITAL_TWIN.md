# PTLC 三维模块 CR5 数字孪生

## 事实源与坐标链

- 实机点位只读来源：`PTLC_CONTROL_ROOT/config/points/robot/robot_points.json`，当前 SHA-256 为
  `4b62a7049b8df0c5e0e8d34920f8cb64695f6dafe73eb04960c3301f9991c673`。
- 运动学与连杆固定到 Dobot 官方提交
  `37730d08b08c74061ae10d4fa5565b4c4c914885`。
- 版本化校准位于 `pipeline/calibration/cr5_ptlc_v1.yaml`。六轴全零占位点不参与拟合。
- 场景统一使用米制 1:1：`机器场景 -> 地轨(1 mm=0.001 m) -> CR5 基座 -> 六轴 FK ->
  Link6 -> TOOL_MOUNT -> 当前工具`，不允许整机全局缩放。
- 地轨 4 号工具工位的实机值为 500 mm；模型在该位置的轴偏移为 0。
- 基座水平平移由 P8/P9/P10 与 CAD 三个工具侧快换原点拟合；竖直高度硬约束为最终整机
  GLB 中机器人地轨托盘的实体上表面 0.178497249 m，不能用旧 CAD 机械臂根节点高度或
  Tool 1 TCP 代替。构建校验会同时检查基座底面接触，以及托盘实体在 X/Z 方向完整覆盖
  基座。实体 Link6→快换接口与控制器 Tool 1 TCP 分开标定，三个工位的实体对接位置
  最大残差 2.6076 mm、姿态最大残差 0.4398°。
- 自制末端几何不以 QT219 零件原点直接重合 TOOL_MOUNT；它保留原始 CAD 的
  Link6 法兰→自制法兰→QT219 刚体关系，再以法兰网格配准到官方 J6。法兰配准
  trimmed RMS 为 0.3087 mm，导出后 Link6 与自制法兰最近顶点距离约 0.039 mm
  （as-built 值；该值精确等于 ICP 标定验收值即证明机器人侧在 CAD 原位）。
- 2026-08-02 起构建期做**快换三维校正（反向吸收）**：TOOL_MOUNT 链（示教点拟合）与
  自制末端 ICP 链互相独立、无交叉校验，两链互差是**三维**的——实测锁紧位横向
  (5.5, 1.1) mm + 轴向端面 4.30 mm（黑盘接触环面悬在母盘顶面上方、插销只入
  凹腔 8.7/13 mm），表现为对接错位 + 端面留缝。`build_robot_joints` 量两个分量：
  横向 = 两半**本体外轮廓**支撑函数配准（`_support_offset_xy`：本体段取离各自配合面
  2~12 mm 的一圈，对每个方向取轮廓最远投影 h(θ)，congruent 形状满足
  h_金−h_黑 = Δ·u(θ)，最小二乘解 Δ 并剔除模块不一致的方向）——**不能用质心**：两半
  挂的模块不一样（金盘多一个 2 路气模块）会系统性拉偏，且配合面处两侧截面根本不可比
  （黑侧插销+倒角 vs 金侧孔口环），质心版实测只纠掉一半（5.5 里纠了 2.96），用户目视
  一眼看穿；轴向 = 实体接触面差（`_contact_plane_z`：按多边形法线取黑盘朝工具侧接触
  环面与母盘顶面，面积加权聚类）。然后**机器人侧保持 CAD/ICP
  原位不动**（臂/自制法兰/黑色快换天生同轴）：TOOL_MOUNT 平移 −delta（三维，落到
  黑盘轴线且端面贴合、插销插到底），工具站（ST_TOOLING：料架+三把刀）按示教位姿下
  的等价世界向量整体平移（横向 ≈3 mm + 竖直 ≈4.3 mm；料架相对机架无参照物，不可见），
  示教点对接保持精确、rig_map `mount_transform` 逐字节不变。耦合轴向 = TOOL_MOUNT
  局部 glTF **Z**（实测金色母盘沿它仅 15 mm 厚；判轴向必须以"母盘薄的方向"实测为准）。
  校正量与残差写入 03 报告 `robot_joints.quick_change_correction`（`mode:
  tool_side_shift`，横向门禁 0.5 mm + 端面门禁 0.5 mm + 配准质量门禁（吻合方向
  ≥50%、残差中位数 ≤0.5 mm），full/raw 两条链同享；raw 无 ST_ 站层级则工具站平移记
  skipped-raw）；`verify_robot_geometry.py` 导出后用独立实现复核
  （`quick_change_lateral_offset_mm` 含 inlier_ratio + `quick_change_face_gap_mm`，同门禁），
  且已并入 app「重跑管线」链（verify-geometry 步）。**验收教训：框架距离≠实体贴合，
  质心≠轴心**——TOOL_MOUNT↔DOCK 框架距离 0.44 mm 的同时端面还差 4.3 mm；换成配合面
  切片质心后端面对了、横向又只纠一半。凡"贴合/对中"断言都必须直接量**共有的实体特征**
  （端面用面积加权平面、横向用同规格轮廓配准），并把吻合度一起报出来。历史：08-01 曾把差
  挪到 Link6↔自制法兰接缝（平移机器人侧），因用户要求三者同轴废弃；08-02 上午只修横向
  （质心法），因插销未入凹槽扩轴向；当日再因残留 2.5 mm 横向错位换成轮廓配准。注意 manifest
  `robot.toolMountTransform` 字段仍原样透传标定值（verify_robot_assets 以 1e-8 断言
  其与标定一致），GLB 中 TOOL_MOUNT 节点的实际局部变换有意与它相差 −delta。
- slot-1/3 示教点对 CAD 料架仍有 2.28/2.61 mm 真实残差，几何上不消除；Studio 播放链
  在锁紧/释放事件带片段时刻走 0.25 s 吸附补间（`MachineStateDriver.lockTool/releaseTool`
  + `updateToolTween`，位姿是片段时间的纯函数，倒放重放可复现），把到位残差做成磁吸
  滑入而不是跳变。实时链 `syncMountedTool` 不走补间，语义不变。

## 构建与校验

在 `three_d` 根目录运行：

```powershell
$env:PTLC_CONTROL_ROOT = 'E:\eit_lab\pTLC_platformUI\eit_ptlc'

python pipeline\calibrate_cr5.py --check
python pipeline\sync_ptlc_robot.py --tool-id 2
python pipeline\03_clean_model.py --stage full --output work\machine.full.glb
python pipeline\verify_robot_geometry.py          # 默认即验收 work\machine.full.glb
node pipeline\04_optimize.mjs --input work\machine.full.glb `
  --output models\machine.official-cr5.glb --no-join
python pipeline\gen_twin_manifest.py --output models\device-manifest.official-cr5.json
python pipeline\verify_robot_assets.py

Copy-Item models\machine.official-cr5.glb app\public\models\machine.official-cr5.glb -Force
Copy-Item models\device-manifest.official-cr5.json `
  app\public\models\device-manifest.official-cr5.json -Force
```

> 2026-08-01 起, 03 之后的资产重建与部署已并入 app「重跑管线」按钮
> (`vite-plugin-authoring.js` 的 `manifest-cr5` / `optimize-cr5` 步骤与 `deployAssets`):
> 它复用主链同一份 `work/machine.full.glb` 喂 `--no-join` 的 04, 两个变体永远同源,
> 不会再出现"两次 03 之间改了代码, 材质页与动画页各看各的模型"的漂移.
> 2026-08-02 起重跑链在 clean 之后加了 `verify-geometry` 步(即 verify_robot_geometry,
> 非零退出中断链). 本节手工配方保留给点表/标定/机器人链变更的场景 ——
> calibrate / sync_ptlc_robot / verify_robot_assets 只在这里跑.
> 注: 旧配方产物 `work\machine.official-cr5.glb` 已无人再写, 是孤儿文件可删.

点表 SHA 或官方提交与校准不一致时，同步器和清单生成会拒绝继续。正式动画只允许
`robot_point`/`operation` 引用；`move_l` 必须带编译期连续 IK 轨迹。

三把刀的几何都在 CAD 里，1=吸盘、2=大夹爪、3=小夹爪均已在 `rig_map.yaml` 的 `tools` 段登记。
1 号吸盘的取法与另外两把不同：`吸盘夹具支架/` 只有一个把工具与料架混在一起的
`玻璃夹具支架装配.SLDASM`，没有像另外两把那样拆成「XX夹具总装(工具) + XX夹具支架总装(料架)」，
所以它用 `members:` 按零件规格聚合散件，而不是 `root:` 抓子装配。

> 2026-08-01 更正：此前本节写着「1=吸盘只有工位快换接口、缺少完整工具几何」，这是错的。
> 零件(QT2091392 工具侧快换 / PTLC-07-006·007·008·009·010 安装板组 / HRQ10A 旋转气缸 /
> 两个 SAB22-KQ2E06 真空吸盘)一直都在模型里，只是散落在 `夹具总装-1` 下、安装板还被
> `join_static_per_station` 并进了 `ST_TOOLING/STATIC_*`。误判的直接后果是实时验收里
> 上位机报 `mounted_tool=1` 时前端法兰空空如也。**判定零件缺失前必须按零件号在 GLB 里
> 扫一遍散落节点，不能只信装配根匹配的结果。**

三把刀共用同一组 `mount_transform`：工具侧快换是纯机械耦合，三个 QT2091392 在 CAD 工具站里
共用一个坐标朝向（本文件 `dock_frame_rotation`）。`blender_clean._check_dock_frames` 把这个
前提做成会失败的断言 —— 实测朝向最大偏差 `0.0396°`、最大偏线 `0.0 mm`，远在 0.5° / 1 mm 门限内。
缺这组值时 `syncMountedTool` 会退回单位四元数，工具绕安装轴错转约 90°。

`sync_ptlc_robot.py` 目前只为 2=大夹爪生成离线片段，Studio 样板默认也是它；1 号与 3 号的
`robot.tool_pickup` / `tool_return` 片段尚未生成（不是资产缺失，是还没做）。

## 实时接口

上位机复用 Dobot 30004 已读取的反馈帧，最高约 20 Hz 发布只读事件，不增加任何控制命令：

```json
{"type":"robot_pose","joint":[0,0,0,0,0,0],"pose":[0,0,0,0,0,0],"tool":2,"ts":0,"seq":1}
```

三维模块使用约 100 ms 缓冲做乱序重排、跨周展开和插值；500 ms 没有新帧后冻结最后姿态并
标记 stale。原 1 Hz `telemetry` 仅在高频流失效时回退。

## 发布边界

> 2026-08-01 更新: 灰度边界已不存在。`machine.glb` 与 `machine.official-cr5.glb` 复用
> 同一份 `work/machine.full.glb`(仅 04 的 `--no-join` 参数不同), 所以 `/3d/materials`、
> `/3d/live` 与 `/3d/motion` 全部是官方 CR5 连杆; 装配台 `/3d/workbench` 的 `raw.glb` 也经
> `03_clean_model.py --stage raw` 换上官方臂(其余零件保持 CAD 原貌供点选授权)。
> 四个视图从此是同一台臂, 不再保留旧 CAD 臂的展示路径。
>
> 同日补充: 官方底座的电缆航插按减配要求在**正式产物中删除**(blender_clean 的
> `strip_base_connector`, 仅 full 链启用), 装配台 raw 链保留全量原貌。装配台的臂
> 摆在 CAD 原安装座位置并静态烘焙 `robot-main.home` 姿态; 正式产物的臂仍在标定
> 参考轨位、零位交给前端驱动 —— 两者位置/姿态语义不同是有意为之。

现场只在原有 DEBUG/安全门约束下操作实机，三维模块被动观察。验收至少覆盖 J1-J6 单轴正负
点动、P8/P9/P10 对接、地轨 500 mm、工具锁紧/释放、断流冻结和角度跨周。
