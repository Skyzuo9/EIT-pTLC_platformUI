# PTLC 三维模块

本目录是 PTLC 上位机三维功能的唯一工程位置, 不再存在独立三维应用或第二套前端仓库.

目录职责:

- `models/`: 上位机直接加载的 GLB、manifest 和成员索引产物.
- `clips/`: 动画片段.
- `generated/`: 前端运行所需的生成数据.
- `pipeline/`: 模型清理、材质生成、绑定生成、压缩和验证管线.
- `docs/`: 三维模型、协议、标定和维护文档.
- `mcp_servers/`: SolidWorks 与 Blender 自动化服务.
- `tools/`: 浏览器验收与视觉检查工具.
- `work/`、`exports/`、`vendor/`: 本地工作产物与第三方依赖, 不进入 Git.

前端实现位于 `eit_ptlc/web/src/three-d/`, 通过 `/api/3d/assets/...` 读取本目录中的资源.

原独立应用的入口、路由和 Vite authoring 中间件不再保留: 页面入口由上位机
`web/src/router.js` 提供, 写回与重建由 `runtime/three_d_authoring.py` 和
`api/three_d_routes.py` 提供, 上位机仍只维护一条 `/api/ws/events` 连接.

## 原始设备文件

SolidWorks 装配、零件、工程图和 STEP 原始文件不进入本仓库. 唯一来源见
[`SOURCE_ASSETS.yaml`](SOURCE_ASSETS.yaml), 当前固定为:

```text
E:/eit_lab/eit_lab_hardware/eit_ptlc_station
```

完整重建前必须先确认该目录存在, 且至少包含 `TLC设备总装.SLDASM` 与 `TLC设备总装.STEP`.

## 验证

```powershell
cd E:/eit_lab/pTLC_platformUI/eit_ptlc/web
npm test
npm run build

cd E:/eit_lab/pTLC_platformUI
& "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_three_d_authoring_offline.py -q
```
