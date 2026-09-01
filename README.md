# pTLC_platform — 制备薄层色谱 (TLC) 全自动化工作站

本仓库经历过多轮重写. 为避免把旧目录当作真源, 此处明确声明各顶层目录的定位.

## 核心 (现役, 唯一真源)

**`eit_ptlc/`** —— 当前核心控制代码 (统一上位机 + 分层 L2 架构). 一切新开发、修改、联调以此为准.

- `eit_ptlc/plc/20260702.project` —— PLC 原生工程 (汇川 InoProShop V1.9.1.6, 制备 TLC 工作站). **PLC 真源**.
- `eit_ptlc/plc/20260702.Device.Application.xml` —— 当前工程的设备/Application XML 导出 (只读检索快照；改 PLC 不直接编辑它，以 `.project` 为准).
- `eit_ptlc/tools/codesys-mcp/` —— 直接读/写/编译 `20260702.project` 的常驻热实例 MCP 工具 (经仓库根 `.mcp.json` 注册为 `codesys`).
- `eit_ptlc/` 其余: `action/` `api/` `controller/` `driver/` `operation/` `runtime/` `web/` 等 —— 上位机控制逻辑与前端.

## 旧版本 / 历史参考 (只读, 勿当真源)

以下顶层目录均为早期版本或迁移资料, 仅作参考, 不参与现役构建:

- `PLCsoftware/` —— 旧 PLC 资料: `CHL-DZ-BJDX-11 ...` 命名工程、`OPCUAtest/*.xml` 旧导出、bootinfo/compileinfo 编译产物.
- `UI-Upper/` —— 旧版上位机实现.
- `unilabos迁移/` —— 迁移分析文档.
- `PLC/`、`View/`、`plc_split/`、`机器人程序/`、`液位检测模块/` —— 早期子系统资料与一次性重构脚本.
- `docs/` —— 设计/交付文档 (部分仍服务于 eit_ptlc, 以正文标注的关联文件为准).

## 约定

- 改 PLC 逻辑: 经 `eit_ptlc/tools/codesys-mcp` 操作 `eit_ptlc/plc/20260702.project`.
- 改控制 / 上位机逻辑: 一律在 `eit_ptlc/` 内.
- 其余顶层目录: 只读参考, 不作为真源, 不在其上继续开发.
