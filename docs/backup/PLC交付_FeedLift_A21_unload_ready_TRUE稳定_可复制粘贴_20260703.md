# PLC交付: FeedLift 光电动作稳定补丁

日期: 2026-07-03

对象: `Application/50_action/FeedLift_L2`

范围: 只改 `A11_feed_raise`、`A21_unload_ready`、`A22_unload_bury` 和 `FeedLift_L2` 局部声明区。不要改 `A12_feed_lower` / `A91_endcheck`。

## 1. 问题与目标

当前 `feedlift.unload_ready` 对应 `FeedLift_L2` 的 `A21_unload_ready`。现有逻辑在找到 `玻璃升降光电开关2 = TRUE` 后，会继续向下寻找 `FALSE` 并要求 `FALSE` 稳定后才 DONE。

现场现象是: 执行 `feedlift.unload_ready` 时，2Z 先抬升，然后一直下降到最低点，最后报错。

这与当前 ST 逻辑一致: 如果下降过程中光电2没有稳定变为 `FALSE`，程序会持续向下搜索，直到 `FeedLift_2Z_SearchLowTarget` 后报 `305`。

同类审查结论:

| 动作 | 是否同类问题 | 处理 |
|---|---|---|
| `A11_feed_raise` | 有弱同类问题: TRUE 抖掉后会继续向上追到 `SearchHighTarget` | 改成停住确认 + 小幅向上重捕获 |
| `A21_unload_ready` | 有明显问题: TRUE 后反向向下追 FALSE | 改成只找 TRUE 稳定接料位 |
| `A22_unload_bury` | 有明显问题: 低位没拿到 FALSE 后会反向扫到 high | 改成只向下找 FALSE 稳定埋料位 |
| `A12_feed_lower` | 非光电搜索动作，只做 1Z 相对下降 5mm | 不改 |
| `A91_endcheck` | DEBUG 静态确认，不 jog | 不改 |

本补丁统一采用:

- 看到目标电平后先停止，再计时确认。
- 稳定确认时间统一为 `T#300MS`。
- 确认中抖掉后，只允许沿原搜索方向小幅重捕获。
- 单次重捕获距离第一版写死为 `2.0`。
- 最大重捕获次数第一版写死为 `2`。
- 不做大范围来回扫。
- 失败仍用原错误码，靠 `FeedLift_L2_Step` 区分阶段。

其中 `A21_unload_ready` 的语义改回:

- `unload_ready` = 找到并停在 `玻璃升降光电开关2 = TRUE` 的稳定接料位。
- 启动时如果光电2已经 TRUE，则原地停住并稳定确认。
- 如果光电2为 FALSE，则只允许向上搜索 TRUE。
- 找到 TRUE 后先停止，再计时确认稳定。
- 稳定确认中如果抖成 FALSE，只允许继续向上小幅重捕获。
- 不向下搜索，不寻找 FALSE，不大范围来回扫。
- `unload_bury` 继续负责机器人放废板后的埋料和最终 FALSE。

## 2. 声明区新增变量

在 `FeedLift_L2` 的局部变量声明区追加:

```iecst
FeedLift_1Z_RaiseRetryCount : INT;
FeedLift_1Z_RaiseStartPos   : LREAL;
FeedLift_2Z_ReadyRetryCount : INT;
FeedLift_2Z_ReadyStartPos   : LREAL;
FeedLift_2Z_BuryRetryCount  : INT;
FeedLift_2Z_BuryStartPos    : LREAL;
```

第一版不新增上位机参数，内部常量直接写在 ST 中:

- 稳定确认时间: `T#300MS`
- 单次重捕获最大距离: `2.0`
- 最大重捕获次数: `2`
- A11 / A21 绝对搜索上界仍使用已有 `FeedLift_*Z_SearchHighTarget`
- A22 绝对搜索下界仍使用已有 `FeedLift_2Z_SearchLowTarget`

## 3. 替换 A11_feed_raise

在 `FeedLift_L2` 下打开 `A11_feed_raise`，用下面 ST 完整替换原动作实现。

```iecst
(* FeedLift feed_raise:
   目标是找到并停在 1Z 上料取料位: 玻璃升降光电开关1 = TRUE。
   - 启动时已 TRUE: 原地停住, 稳定确认 DONE。
   - 启动时 FALSE: 只向上搜索 TRUE。
   - 看到 TRUE 后先停住, 再计时确认。
   - 确认中抖成 FALSE: 只向上小幅重捕获。
   - 失败用 304, 通过 FeedLift_L2_Step 区分阶段。 *)
CASE 上料step OF
	0:
		FeedLift_L2_Step := 11;  (* 初始化 / 前置检查 *)
		Z1JOG_pos := FALSE;
		feedlift_TO(IN := FALSE, PT := T#300MS);
		FeedLift_1Z_RaiseRetryCount := 0;
		FeedLift_1Z_RaiseStartPos := 玻璃上料轴1ZDATE.fActPos;

		IF FeedLift_1Z_SearchLowTarget >= FeedLift_1Z_SearchHighTarget THEN
			FeedLift_L2_ErrorCode := 303;
			上料step := 0;
			bActionError := TRUE;
		ELSE
			上料step := 5;
		END_IF

	5:
		FeedLift_L2_Step := 11;  (* 等待前置条件满足 *)
		Z1JOG_pos := FALSE;

		IF 玻璃上料轴1ZDATE.bHomed AND 玻璃升降接近开关1 AND 上料进料传感器 AND NOT Alarm.0 THEN
			feedlift_TO(IN := FALSE, PT := T#300MS);
			IF 玻璃升降光电开关1 THEN
				上料step := 20;
			ELSE
				上料step := 10;
			END_IF
		ELSE
			feedlift_TO(IN := TRUE, PT := T#10S);
			IF feedlift_TO.Q THEN
				FeedLift_L2_ErrorCode := 301;
				上料step := 0;
				bActionError := TRUE;
			END_IF
		END_IF

	10:
		FeedLift_L2_Step := 11;  (* 向上搜索 TRUE *)
		feedlift_TO(IN := FALSE, PT := T#300MS);

		IF 玻璃升降光电开关1 THEN
			Z1JOG_pos := FALSE;
			上料step := 20;
		ELSIF 玻璃上料轴1ZDATE.fActPos < FeedLift_1Z_SearchHighTarget THEN
			Z1JOG_pos := TRUE;
		ELSE
			Z1JOG_pos := FALSE;
			FeedLift_L2_Step := 14;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 304;
			上料step := 0;
			bActionError := TRUE;
		END_IF

	20:
		FeedLift_L2_Step := 12;  (* 停住后确认 TRUE 稳定 *)
		Z1JOG_pos := FALSE;
		feedlift_TO(IN := 玻璃升降光电开关1, PT := T#300MS);

		IF feedlift_TO.Q THEN
			上料step := 0;
			bActionDone := TRUE;
		ELSIF NOT 玻璃升降光电开关1 THEN
			feedlift_TO(IN := FALSE, PT := T#300MS);
			IF FeedLift_1Z_RaiseRetryCount < 2 THEN
				FeedLift_1Z_RaiseRetryCount := FeedLift_1Z_RaiseRetryCount + 1;
				FeedLift_1Z_RaiseStartPos := 玻璃上料轴1ZDATE.fActPos;
				上料step := 30;
			ELSE
				FeedLift_L2_Step := 14;  (* 失败收敛 *)
				FeedLift_L2_ErrorCode := 304;
				上料step := 0;
				bActionError := TRUE;
			END_IF
		END_IF

	30:
		FeedLift_L2_Step := 13;  (* 小幅向上重捕获 TRUE *)
		feedlift_TO(IN := FALSE, PT := T#300MS);

		IF 玻璃升降光电开关1 THEN
			Z1JOG_pos := FALSE;
			上料step := 20;
		ELSIF 玻璃上料轴1ZDATE.fActPos >= FeedLift_1Z_SearchHighTarget THEN
			Z1JOG_pos := FALSE;
			FeedLift_L2_Step := 14;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 304;
			上料step := 0;
			bActionError := TRUE;
		ELSIF (玻璃上料轴1ZDATE.fActPos - FeedLift_1Z_RaiseStartPos) >= 2.0 THEN
			Z1JOG_pos := FALSE;
			FeedLift_L2_Step := 14;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 304;
			上料step := 0;
			bActionError := TRUE;
		ELSE
			Z1JOG_pos := TRUE;
		END_IF
END_CASE
```

## 4. 替换 A21_unload_ready

在 `FeedLift_L2` 下打开 `A21_unload_ready`，用下面 ST 完整替换原动作实现。

```iecst
(* FeedLift unload_ready:
   目标是找到并停在 2Z 废料接料位: 玻璃升降光电开关2 = TRUE。
   - 启动时已 TRUE: 原地停住, 稳定确认 DONE。
   - 启动时 FALSE: 只向上搜索 TRUE。
   - 看到 TRUE 后先停住, 再计时确认。
   - 确认中抖成 FALSE: 只向上小幅重捕获, 不向下搜索。
   - 失败统一报 305, 通过 FeedLift_L2_Step 区分阶段。 *)
CASE 下料step OF
	0:
		FeedLift_L2_Step := 21;  (* 初始化 / 前置检查 *)
		Z2JOG_POS := FALSE;
		Z2JOG_NEG := FALSE;
		feedlift_TO(IN := FALSE, PT := T#300MS);
		FeedLift_2Z_ReadyRetryCount := 0;
		FeedLift_2Z_ReadyStartPos := 玻璃上料轴2ZDATE.fActPos;

		IF FeedLift_2Z_SearchLowTarget >= FeedLift_2Z_SearchHighTarget THEN
			FeedLift_L2_ErrorCode := 303;
			下料step := 0;
			bActionError := TRUE;
		ELSE
			下料step := 5;
		END_IF

	5:
		FeedLift_L2_Step := 21;  (* 等待前置条件满足 *)
		Z2JOG_POS := FALSE;
		Z2JOG_NEG := FALSE;

		IF 玻璃上料轴2ZDATE.bHomed AND 下料出料传感器 AND NOT Alarm.1 THEN
			feedlift_TO(IN := FALSE, PT := T#300MS);
			IF 玻璃升降光电开关2 THEN
				下料step := 20;
			ELSE
				下料step := 10;
			END_IF
		ELSE
			feedlift_TO(IN := TRUE, PT := T#10S);
			IF feedlift_TO.Q THEN
				FeedLift_L2_ErrorCode := 302;
				下料step := 0;
				bActionError := TRUE;
			END_IF
		END_IF

	10:
		FeedLift_L2_Step := 21;  (* 向上搜索 TRUE *)
		Z2JOG_NEG := FALSE;
		feedlift_TO(IN := FALSE, PT := T#300MS);

		IF 玻璃升降光电开关2 THEN
			Z2JOG_POS := FALSE;
			下料step := 20;
		ELSIF 玻璃上料轴2ZDATE.fActPos < FeedLift_2Z_SearchHighTarget THEN
			Z2JOG_POS := TRUE;
		ELSE
			Z2JOG_POS := FALSE;
			FeedLift_L2_Step := 24;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 305;
			下料step := 0;
			bActionError := TRUE;
		END_IF

	20:
		FeedLift_L2_Step := 22;  (* 停住后确认 TRUE 稳定 *)
		Z2JOG_POS := FALSE;
		Z2JOG_NEG := FALSE;
		feedlift_TO(IN := 玻璃升降光电开关2, PT := T#300MS);

		IF feedlift_TO.Q THEN
			下料step := 0;
			bActionDone := TRUE;
		ELSIF NOT 玻璃升降光电开关2 THEN
			feedlift_TO(IN := FALSE, PT := T#300MS);
			IF FeedLift_2Z_ReadyRetryCount < 2 THEN
				FeedLift_2Z_ReadyRetryCount := FeedLift_2Z_ReadyRetryCount + 1;
				FeedLift_2Z_ReadyStartPos := 玻璃上料轴2ZDATE.fActPos;
				下料step := 30;
			ELSE
				FeedLift_L2_Step := 24;  (* 失败收敛 *)
				FeedLift_L2_ErrorCode := 305;
				下料step := 0;
				bActionError := TRUE;
			END_IF
		END_IF

	30:
		FeedLift_L2_Step := 23;  (* 小幅向上重捕获 TRUE *)
		Z2JOG_NEG := FALSE;
		feedlift_TO(IN := FALSE, PT := T#300MS);

		IF 玻璃升降光电开关2 THEN
			Z2JOG_POS := FALSE;
			下料step := 20;
		ELSIF 玻璃上料轴2ZDATE.fActPos >= FeedLift_2Z_SearchHighTarget THEN
			Z2JOG_POS := FALSE;
			FeedLift_L2_Step := 24;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 305;
			下料step := 0;
			bActionError := TRUE;
		ELSIF (玻璃上料轴2ZDATE.fActPos - FeedLift_2Z_ReadyStartPos) >= 2.0 THEN
			Z2JOG_POS := FALSE;
			FeedLift_L2_Step := 24;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 305;
			下料step := 0;
			bActionError := TRUE;
		ELSE
			Z2JOG_POS := TRUE;
		END_IF
END_CASE
```

## 5. 替换 A22_unload_bury

在 `FeedLift_L2` 下打开 `A22_unload_bury`，用下面 ST 完整替换原动作实现。

```iecst
(* FeedLift unload_bury:
   目标是机器人放废板后, 2Z 向下埋料直到 玻璃升降光电开关2 = FALSE。
   - 启动时已 FALSE: 原地停住, 稳定确认 DONE。
   - 启动时 TRUE: 只向下搜索 FALSE。
   - 看到 FALSE 后先停住, 再计时确认。
   - 确认中抖成 TRUE: 只向下小幅重捕获, 不反向上扫。
   - 失败用 305, 通过 FeedLift_L2_Step 区分阶段。 *)
CASE 下料step OF
	0:
		FeedLift_L2_Step := 31;  (* 初始化 / 前置检查 *)
		Z2JOG_POS := FALSE;
		Z2JOG_NEG := FALSE;
		feedlift_TO(IN := FALSE, PT := T#300MS);
		FeedLift_2Z_BuryRetryCount := 0;
		FeedLift_2Z_BuryStartPos := 玻璃上料轴2ZDATE.fActPos;

		IF FeedLift_2Z_SearchLowTarget >= FeedLift_2Z_SearchHighTarget THEN
			FeedLift_L2_ErrorCode := 303;
			下料step := 0;
			bActionError := TRUE;
		ELSE
			下料step := 5;
		END_IF

	5:
		FeedLift_L2_Step := 31;  (* 等待前置条件满足 *)
		Z2JOG_POS := FALSE;
		Z2JOG_NEG := FALSE;

		IF 玻璃上料轴2ZDATE.bHomed AND 玻璃升降接近开关2 AND NOT Alarm.1 THEN
			feedlift_TO(IN := FALSE, PT := T#300MS);
			IF NOT 玻璃升降光电开关2 THEN
				下料step := 20;
			ELSE
				下料step := 10;
			END_IF
		ELSE
			feedlift_TO(IN := TRUE, PT := T#10S);
			IF feedlift_TO.Q THEN
				FeedLift_L2_ErrorCode := 302;
				下料step := 0;
				bActionError := TRUE;
			END_IF
		END_IF

	10:
		FeedLift_L2_Step := 31;  (* 向下搜索 FALSE *)
		Z2JOG_POS := FALSE;
		feedlift_TO(IN := FALSE, PT := T#300MS);

		IF NOT 玻璃升降光电开关2 THEN
			Z2JOG_NEG := FALSE;
			下料step := 20;
		ELSIF 玻璃上料轴2ZDATE.fActPos > FeedLift_2Z_SearchLowTarget THEN
			Z2JOG_NEG := TRUE;
		ELSE
			Z2JOG_NEG := FALSE;
			FeedLift_L2_Step := 34;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 305;
			下料step := 0;
			bActionError := TRUE;
		END_IF

	20:
		FeedLift_L2_Step := 32;  (* 停住后确认 FALSE 稳定 *)
		Z2JOG_POS := FALSE;
		Z2JOG_NEG := FALSE;
		feedlift_TO(IN := NOT 玻璃升降光电开关2, PT := T#300MS);

		IF feedlift_TO.Q THEN
			下料step := 0;
			bActionDone := TRUE;
		ELSIF 玻璃升降光电开关2 THEN
			feedlift_TO(IN := FALSE, PT := T#300MS);
			IF FeedLift_2Z_BuryRetryCount < 2 THEN
				FeedLift_2Z_BuryRetryCount := FeedLift_2Z_BuryRetryCount + 1;
				FeedLift_2Z_BuryStartPos := 玻璃上料轴2ZDATE.fActPos;
				下料step := 30;
			ELSE
				FeedLift_L2_Step := 34;  (* 失败收敛 *)
				FeedLift_L2_ErrorCode := 305;
				下料step := 0;
				bActionError := TRUE;
			END_IF
		END_IF

	30:
		FeedLift_L2_Step := 33;  (* 小幅向下重捕获 FALSE *)
		Z2JOG_POS := FALSE;
		feedlift_TO(IN := FALSE, PT := T#300MS);

		IF NOT 玻璃升降光电开关2 THEN
			Z2JOG_NEG := FALSE;
			下料step := 20;
		ELSIF 玻璃上料轴2ZDATE.fActPos <= FeedLift_2Z_SearchLowTarget THEN
			Z2JOG_NEG := FALSE;
			FeedLift_L2_Step := 34;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 305;
			下料step := 0;
			bActionError := TRUE;
		ELSIF (FeedLift_2Z_BuryStartPos - 玻璃上料轴2ZDATE.fActPos) >= 2.0 THEN
			Z2JOG_NEG := FALSE;
			FeedLift_L2_Step := 34;  (* 失败收敛 *)
			FeedLift_L2_ErrorCode := 305;
			下料step := 0;
			bActionError := TRUE;
		ELSE
			Z2JOG_NEG := TRUE;
		END_IF
END_CASE
```

## 6. 在线观察点

执行 FeedLift 光电动作时重点看:

| 变量 | 期望 |
|---|---|
| `FeedLift_L2_ActiveCode` | `11` / `21` / `22` |
| `FeedLift_L2_Step` | A11: `11/12/13/14`; A21: `21/22/23/24`; A22: `31/32/33/34` |
| `玻璃升降光电开关1` | A11 DONE 时应为 `TRUE` |
| `玻璃升降光电开关2` | A21 DONE 时应为 `TRUE`; A22 DONE 时应为 `FALSE` |
| `Z1JOG_pos` | 只允许 A11 搜索或重捕获时短暂 TRUE |
| `Z2JOG_POS` | 只允许 A21 搜索或重捕获时短暂 TRUE; A22 中应始终 FALSE |
| `Z2JOG_NEG` | 只允许 A22 搜索或重捕获时短暂 TRUE; A21 中应始终 FALSE |
| `FeedLift_L2_ErrorCode` | 非法窗口为 `303`; 前置条件超时为 `301/302`; 找不到稳定目标电平为 `304/305` |

## 7. 验收顺序

1. 编译 PLC，必须 0 errors。
2. 手动确认:
   - `FeedLift_1Z_SearchLowTarget < FeedLift_1Z_SearchHighTarget`
   - `FeedLift_2Z_SearchLowTarget < FeedLift_2Z_SearchHighTarget`
3. 单独执行 `feedlift.feed_raise`:
   - 1Z 已经处于光电1 TRUE 时，应原地稳定确认 DONE。
   - 1Z 处于光电1 FALSE 且安全低位时，只允许向上运动。
   - 看到 TRUE 后停止，停稳确认后 DONE。
   - TRUE 抖掉时只允许向上小幅重捕获，失败报 304。
4. 让 2Z 处于光电2已经 TRUE 的位置，执行 `feedlift.unload_ready`:
   - 期望不运动。
   - `FeedLift_L2_Step` 进入 `22`。
   - TRUE 稳定 300ms 后 DONE。
5. 让 2Z 处于光电2 FALSE 且安全低位，执行 `feedlift.unload_ready`:
   - 只允许向上运动。
   - 看到 TRUE 后停止。
   - 停稳确认后 DONE。
6. 人为造成 A21 光电2抖动:
   - 只允许向上小幅重捕获。
   - 不允许向下运动。
   - 超过 2 次或单次超过 2.0 后报 305。
7. 单独执行 `feedlift.unload_bury`:
   - 2Z 已经处于光电2 FALSE 时，应原地稳定确认 DONE。
   - 2Z 处于光电2 TRUE 时，只允许向下运动。
   - 看到 FALSE 后停止，停稳确认后 DONE。
   - FALSE 抖掉时只允许向下小幅重捕获。
   - 不允许出现 `Z2JOG_POS = TRUE` 的反向上扫。
8. 单动作通过后，再跑 `feedlift_load_cycle`:
   - `feedlift.feed_raise` 到取料位。
   - 机器人吸板。
   - `feedlift.feed_lower` 相对下降让位。
9. 最后跑 `feedlift_unload_cycle`:
   - `unload_ready` 到接料位。
   - 机器人放废板。
   - `unload_bury` 再执行埋料至 FALSE。

## 8. 回滚点

如果该补丁现场表现不符合机械语义，只回滚四处:

1. 删除本补丁新增的 6 个局部变量:
   - `FeedLift_1Z_RaiseRetryCount`
   - `FeedLift_1Z_RaiseStartPos`
   - `FeedLift_2Z_ReadyRetryCount`
   - `FeedLift_2Z_ReadyStartPos`
   - `FeedLift_2Z_BuryRetryCount`
   - `FeedLift_2Z_BuryStartPos`
2. 把 `A11_feed_raise` 恢复为原实现。
3. 把 `A21_unload_ready` 恢复为原实现。
4. 把 `A22_unload_bury` 恢复为原实现。

`A12_feed_lower` 和 `A91_endcheck` 未修改，不在回滚范围。
