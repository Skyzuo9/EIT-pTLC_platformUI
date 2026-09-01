/**
 * 功能: PLC L2 动作码 / 错误码 / 段号的中文释义 —— **本文件由脚本生成, 不要手改**.
 *
 * 生成器: eit_ptlc/tools/gen_plc_semantics.py
 * 真源:   eit_ptlc/mock/behavior/specs/*.yaml (从 CODESYS 现役工程逐字提取)
 * 看门狗: eit_ptlc/tests/test_plc_semantics_gen_offline.py (逐字节比对, 手改必红)
 *
 * 改法: 改真源 yaml, 然后
 *   & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tools.gen_plc_semantics
 *
 * 形状: { <工位L2前缀>: { unknownCodeError, gateErrors:{码:中文},
 *                        actions: { <动作码>: { name, summary, steps:[[段号,phase]], errors:{码:中文} } } } }
 * 注意 steps 里的 phase 是英文蛇形原文 —— 刻意不译, 只给工程师层看.
 */

export const PLC_SEMANTICS = Object.freeze({
  "Collect": {
    "actions": {
      "10": {
        "errors": {},
        "name": "A10_init_初始化",
        "steps": [
          [
            0,
            "reset_outputs_send_pump_init"
          ],
          [
            10,
            "poll_pump_until_idle_edge"
          ],
          [
            20,
            "wait_four_homes_and_pump"
          ]
        ],
        "summary": "清全部收集输出位, 初始化 3 号注射泵, 等四气缸原点齐备"
      },
      "21": {
        "errors": {},
        "name": "A21_夹持夹紧",
        "steps": [
          [
            0,
            "set_clamp_output"
          ],
          [
            10,
            "wait_clamp_work_pos"
          ]
        ],
        "summary": "夹持气缸夹紧收集器 (上位机已先驱动机器人放收集器)"
      },
      "22": {
        "errors": {},
        "name": "A22_伸缩伸出",
        "steps": [
          [
            0,
            "gate_then_set_extend_output"
          ],
          [
            10,
            "wait_push_work_pos"
          ]
        ],
        "summary": "伸缩气缸伸出到放瓶位 (要求放瓶位当前无瓶)"
      },
      "23": {
        "errors": {
          "201": "缺瓶: 伸缩缩回到原点的判定扫描上 收集平台瓶子有无传感器=FALSE; 上位机重放瓶后重调"
        },
        "name": "A23_缩回升降下压",
        "steps": [
          [
            0,
            "clear_extend_output"
          ],
          [
            10,
            "check_bottle_then_lift"
          ],
          [
            20,
            "wait_lift_then_press_done"
          ]
        ],
        "summary": "伸缩缩回 -> 缺瓶判定 -> 升降上升 -> 下压 (下压不等到位)"
      },
      "24": {
        "errors": {},
        "name": "内联_溶液收集瓶定位",
        "steps": [],
        "summary": "直写瓶定位气缸目标态并同扫描完成 (遗留通道)"
      },
      "30": {
        "errors": {},
        "name": "A30_collect_收集",
        "steps": [
          [
            0,
            "open_intake_send_pump_cmd"
          ],
          [
            10,
            "poll_pump_until_idle_edge"
          ],
          [
            20,
            "switch_to_drain_single_scan"
          ],
          [
            30,
            "drain_then_settle_decide"
          ],
          [
            40,
            "close_drain_done"
          ]
        ],
        "summary": "进液 + 注射泵转发 -> 排液 20s + 沉淀 5s, 循环 collect_count 次"
      },
      "41": {
        "errors": {},
        "name": "A41_复位伸出",
        "steps": [
          [
            0,
            "clear_press_output"
          ],
          [
            5,
            "wait_press_home_clear_lift"
          ],
          [
            10,
            "wait_lift_home_set_extend"
          ],
          [
            20,
            "wait_push_work_pos"
          ]
        ],
        "summary": "复位下压 -> 复位升降 -> 伸缩伸出到取瓶位"
      },
      "42": {
        "errors": {},
        "name": "A42_伸缩缩回",
        "steps": [
          [
            0,
            "clear_extend_output"
          ],
          [
            10,
            "wait_push_home"
          ]
        ],
        "summary": "伸缩缩回 (上位机已先驱动机器人取瓶到暂存)"
      },
      "43": {
        "errors": {},
        "name": "A43_松夹持",
        "steps": [
          [
            0,
            "clear_clamp_output"
          ],
          [
            10,
            "wait_clamp_home"
          ]
        ],
        "summary": "松开夹持气缸 (上位机已先驱动机器人到收集器位)"
      }
    },
    "gateErrors": {},
    "unknownCodeError": 101
  },
  "Develop": {
    "actions": {
      "10": {
        "errors": {},
        "name": "A10_init_初始化",
        "steps": [],
        "summary": "清零所选缸全部阀/气缸输出并向组泵发 Z0,2,2R 初始化, 等泵空闲上升沿完成"
      },
      "20": {
        "errors": {},
        "name": "A20_pipeline_清洗管路",
        "steps": [],
        "summary": "单次转发上位机生成的泵指令串清洗管路, 泵空闲后静置 3s 置 Expand_Group_clean_OK"
      },
      "21": {
        "errors": {},
        "name": "A21_rinse_润洗展缸",
        "steps": [],
        "summary": "开进液/排液阀与气缸后按 Expand_rinse_count 循环转发泵指令注液, 末次泵空闲静置 5s, 阀位保持交接 A26"
      },
      "22": {
        "errors": {},
        "name": "A22_up_liquid_上液",
        "steps": [],
        "summary": "开进液阀按 Expand_up_liquid_count 循环转发泵指令上液, 计数达标关进液阀置 Expand_up_liquid_OK"
      },
      "26": {
        "errors": {
          "402": "抽吸超时 (沉降期满后 cap_s 看门狗到期而废液走空判据始终未连续满足)"
        },
        "name": "A26_rinse_suction",
        "steps": [],
        "summary": "承接 A21 阀位的润洗抽吸四相, 沉降 -> 废液走空判据 -> 关进液开吹气 -> 吹扫到时关阀完成"
      },
      "31": {
        "errors": {},
        "name": "A31_放板缸回原点",
        "steps": [],
        "summary": "所选缸气缸自动输出置 FALSE, 持续等原点反馈成立 (开盖, 供机器人放/取板)"
      },
      "32": {
        "errors": {},
        "name": "A32_放板缸到动点",
        "steps": [],
        "summary": "所选缸气缸自动输出置 TRUE, 持续等动点反馈成立 (关盖, 机器人放板退出后调用)"
      },
      "50": {
        "errors": {
          "501": "接受门拒绝 (Tank_State 10/90 不可排液)",
          "502": "排液 FSM 错误态 (RUNNING 中 Tank_State=90, 由急停联锁置入)"
        },
        "name": "A50_Expand_liquid_discharge_排液",
        "steps": [],
        "summary": "展缸排液四相 (50->55->56->98), mock 已实现 (plc_server.run_tank_drain_fsm)"
      },
      "51": {
        "errors": {
          "511": "缸态不可释放 (接受门与 RUNNING 复检同用此码)"
        },
        "name": "release_tank_释放缸资源",
        "steps": [],
        "summary": "释放已排空缸资源 (Tank_State 归 0), 内联于派发器, 同一扫描完成"
      }
    },
    "gateErrors": {
      "102": "目标缸号越界 (Expand_Target_Tank 不在 1..8, REJECTED)",
      "190": "部署/就绪门拒绝 (Start 沿且 IDLE 时 NOT PLC_Ready 或 PLC_Deploy_State<>0, 先于一切检查, REJECTED)"
    },
    "unknownCodeError": 101
  },
  "FeedLift": {
    "actions": {
      "10": {
        "errors": {
          "308": "5 秒内双轴未同时 bHomed (只报错交上位机, **PLC 不自行 Home**)"
        },
        "name": "A10_init_初始化",
        "steps": [
          [
            51,
            "clear_residual_commands"
          ],
          [
            52,
            "check_homed"
          ],
          [
            54,
            "fail"
          ]
        ],
        "summary": "清 L2 域内残留命令位, 再校验 1Z/2Z 已回零; 本动作不产生任何轴运动"
      },
      "11": {
        "errors": {
          "301": "前置门 10 秒未满足 (未回零 / 空仓 / 无料 / Alarm.0)",
          "303": "搜索区间非法 (SearchLowTarget >= SearchHighTarget)",
          "304": "向上搜到 SearchHighTarget 仍未见光电 TRUE"
        },
        "name": "A11_feed_raise",
        "steps": [
          [
            11,
            "preflight_and_search_up"
          ],
          [
            12,
            "confirm_stable"
          ],
          [
            13,
            "recapture_up"
          ],
          [
            14,
            "fail"
          ]
        ],
        "summary": "1Z 向上搜索至 玻璃升降光电开关1 = TRUE (上料取料位), 停住后 300ms 稳定确认"
      },
      "12": {
        "errors": {},
        "name": "A12_feed_lower",
        "steps": [],
        "summary": "机器人吸住玻璃后, 1Z 相对下降 5mm 让位"
      },
      "13": {
        "errors": {
          "301": "前置门 10 秒未满足",
          "303": "搜索区间非法 (SearchLowTarget >= SearchHighTarget)",
          "307": "向下搜到 SearchLowTarget 仍未见光电 FALSE, 或重捕获超限/超 2.0mm"
        },
        "name": "A13_feed_clear",
        "steps": [
          [
            41,
            "preflight_and_search_down"
          ],
          [
            42,
            "confirm_stable"
          ],
          [
            43,
            "recapture_down"
          ],
          [
            44,
            "fail"
          ]
        ],
        "summary": "1Z 向下退到 玻璃升降光电开关1 = FALSE, 给随后的 feed_raise 让出\"从 FALSE 侧逼近\"的行程"
      },
      "21": {
        "errors": {
          "302": "前置门 10 秒未满足 (未回零 / 出料传感器无信号 / Alarm.1)",
          "303": "搜索区间非法",
          "305": "向上搜到 SearchHighTarget 仍未见光电 TRUE, 或重捕获超限"
        },
        "name": "A21_unload_ready",
        "steps": [
          [
            21,
            "preflight_and_search_up"
          ],
          [
            22,
            "confirm_stable"
          ],
          [
            23,
            "recapture_up"
          ],
          [
            24,
            "fail"
          ]
        ],
        "summary": "2Z 向上搜索至 玻璃升降光电开关2 = TRUE (废料接料位)"
      },
      "22": {
        "errors": {
          "302": "前置门 10 秒未满足",
          "303": "搜索区间非法",
          "305": "向下搜到 SearchLowTarget 仍未见光电 FALSE, 或重捕获超限/超 2.0mm"
        },
        "name": "A22_unload_bury",
        "steps": [
          [
            31,
            "preflight_and_search_down"
          ],
          [
            32,
            "confirm_stable"
          ],
          [
            33,
            "recapture_down"
          ],
          [
            34,
            "fail"
          ]
        ],
        "summary": "机器人放废板后, 2Z 向下埋料直到 玻璃升降光电开关2 = FALSE"
      },
      "91": {
        "errors": {
          "306": "FeedLift_DebugAxis 非 1/2"
        },
        "name": "A91_endcheck",
        "steps": [
          [
            91,
            "debug_confirm"
          ]
        ],
        "summary": "DEBUG 用 —— 不动轴, 只确认指定轴的光电稳定处于 FeedLift_DebugExpectedFinal"
      }
    },
    "gateErrors": {
      "190": "全局部署门 (NOT PLC_Ready 或 PLC_Deploy_State<>0), 在任何物理动作派发前拒绝"
    },
    "unknownCodeError": 101
  },
  "PhotoScrape": {
    "actions": {
      "10": {
        "errors": {},
        "name": "A10_init_初始化",
        "steps": [
          [
            0,
            "clear_all_outputs_and_handshake_flags"
          ],
          [
            5,
            "clear_axis_moveabs_residue"
          ],
          [
            6,
            "z10_moveabs_to_0"
          ],
          [
            10,
            "x9_moveabs_to_335"
          ],
          [
            20,
            "shade_upper_gate_then_y8_moveabs_to_0"
          ]
        ],
        "summary": "清 7 个执行件全部手/自动输出与交接标志, 再按 10Z->0, 9X->335, (遮光上位门) 8Y->0 顺序归位."
      },
      "31": {
        "errors": {},
        "name": "A31_cam_移轴335",
        "steps": [],
        "summary": "刮板 9X 绝对移动到 335 (放板/上料让位), bAbMoveDone 后撤令 DONE."
      },
      "32": {
        "errors": {},
        "name": "A32_cam_定位",
        "steps": [],
        "summary": "定位气缸目标态直写, 同扫描 DONE, 不读反馈."
      },
      "33": {
        "errors": {},
        "name": "A33_cam_下压",
        "steps": [],
        "summary": "下压气缸双向不对称, TRUE 置位即同扫描 DONE, FALSE 清位后等上位反馈才 DONE."
      },
      "34": {
        "errors": {},
        "name": "A34_cam_相机位",
        "steps": [
          [
            0,
            "shade_upper_gate_then_y8_moveabs_to_photo_target"
          ],
          [
            10,
            "y8_done_then_shade_down_cmd"
          ],
          [
            20,
            "wait_shade_lower_feedback"
          ]
        ],
        "summary": "遮光上位门内 8Y 移到 Photo_8Y_Target, 到位后遮光下, 等下位反馈 DONE (拍照本身归上位机)."
      },
      "35": {
        "errors": {},
        "name": "A35_cam_回零",
        "steps": [
          [
            0,
            "shade_up_cmd"
          ],
          [
            10,
            "wait_shade_upper_then_y8_moveabs_to_0"
          ],
          [
            20,
            "wait_y8_done"
          ]
        ],
        "summary": "清遮光输出 (遮光上), 等上位反馈后 8Y 回 0, bAbMoveDone 后 DONE."
      },
      "36": {
        "errors": {},
        "name": "粉末收集器定位_派发器内联",
        "steps": [],
        "summary": "粉末收集器定位气缸目标态直写, 同扫描 DONE (派发器 RUNNING CASE 内联单行)."
      },
      "40": {
        "errors": {},
        "name": "A40_scrape_刮取",
        "steps": [
          [
            0,
            "vacuum_on_motor_on_cnc_start"
          ],
          [
            10,
            "wait_cnc_done_then_clear_start"
          ]
        ],
        "summary": "开真空阀+无刷电机并置 CNC启动, 黑盒等待内部 CNC完成 后撤启动 DONE (真空/电机保持开)."
      },
      "41": {
        "errors": {},
        "name": "A41_scrape_收尾",
        "steps": [],
        "summary": "关真空+关无刷电机+旋转气缸置位翻料, 同扫描 DONE, 不读任何反馈."
      },
      "42": {
        "errors": {
          "421": "Z 非零位禁 XY 移动, 先 align_z(0) 抬起",
          "422": "XY 目标在板区软限位窗外 (窗未实测回填前恒拒动, 安全默认)",
          "425": "遮光未上位, 8Y 硬互锁不放行, 先 cam_photohome(35)"
        },
        "name": "align_move_对位XY_派发器内联",
        "steps": [
          [
            0,
            "clear_moveabs_then_guards_then_move_xy"
          ],
          [
            10,
            "wait_both_done_restore_velocity"
          ]
        ],
        "summary": "守卫通过后 9X/8Y 以 40 mm/s 同动到帧变换后的 Target, 双轴到位恢复速度并停在原地不回零."
      },
      "43": {
        "errors": {
          "425": "遮光未上位, 8Y 回零会被硬互锁挂死, 先 cam_photohome(35)"
        },
        "name": "align_home_对位回零_派发器内联",
        "steps": [
          [
            0,
            "clear_moveabs_then_shade_upper_guard"
          ],
          [
            5,
            "z10_moveabs_to_0"
          ],
          [
            10,
            "x9_moveabs_to_335"
          ],
          [
            20,
            "shade_interlock_recheck_then_y8_moveabs_to_0"
          ]
        ],
        "summary": "遮光上位门内按 10Z->0, 9X->335, 8Y->0 顺序 MoveAbsolute 归位, 不走 MC_Home."
      },
      "44": {
        "errors": {
          "421": "Z 目标越档, 允许 [0, ALIGN_Z_CHECK_MAX]",
          "424": "降 Z 前置 XY 须在板区窗内 (窗未回填前恒拒动)"
        },
        "name": "align_z_对位Z_派发器内联",
        "steps": [
          [
            0,
            "range_and_window_guards_then_z10_slow_move"
          ],
          [
            10,
            "wait_done_restore_velocity"
          ]
        ],
        "summary": "10Z 以 5 mm/s 慢速绝对移动到 [0,18] 内目标, 降向须 XY 在板区窗内, 完成恢复速度."
      },
      "51": {
        "errors": {},
        "name": "A51_取料松压",
        "steps": [],
        "summary": "清下压气缸输出, 等上位反馈 DONE (机器人到收集器夹持位后松压)."
      },
      "52": {
        "errors": {},
        "name": "A52_取料停旋转",
        "steps": [],
        "summary": "清旋转气缸输出, 同扫描 DONE, 不读反馈 (机器人取走收集器后收尾)."
      }
    },
    "gateErrors": {},
    "unknownCodeError": 101
  },
  "Pump": {
    "actions": {
      "10": {
        "errors": {},
        "name": "A10_vacuum_on",
        "steps": [],
        "summary": "置上位机泵槽 大真空泵站位[11] := TRUE, 同扫描 DONE"
      },
      "20": {
        "errors": {},
        "name": "A20_vacuum_off",
        "steps": [],
        "summary": "清上位机泵槽 大真空泵站位[11] := FALSE, 同扫描 DONE"
      }
    },
    "gateErrors": {
      "190": "全局部署门 (NOT PLC_Ready 或 PLC_Deploy_State<>0), 在任何物理动作派发前拒绝"
    },
    "unknownCodeError": 101
  },
  "Rail": {
    "actions": {
      "10": {
        "errors": {
          "101": "未知动作码 或 位置码越界 (retryable)",
          "102": "目标未初始化或越限 (fTgt <= 0 或 > 3000, retryable)"
        },
        "name": "A10_rail_move (内联于派发器)",
        "steps": [],
        "summary": "按位置码把地轨 11Y 移到 Rail_Pos_Target[Rail_Target_Position] (PC 真源坐标)"
      }
    },
    "gateErrors": {
      "190": "全局部署门 (NOT PLC_Ready 或 PLC_Deploy_State<>0), 在任何物理动作派发前拒绝"
    },
    "unknownCodeError": 101
  },
  "Sampling": {
    "actions": {
      "10": {
        "errors": {},
        "name": "A10_init_初始化",
        "steps": [
          [
            0,
            "reset_outputs_and_flags"
          ],
          [
            5,
            "z5_home_then_start_xy_home"
          ],
          [
            6,
            "wait_all_axes_home"
          ],
          [
            10,
            "pump_init_send"
          ],
          [
            20,
            "pump_init_poll_idle"
          ],
          [
            30,
            "set_ok_and_done"
          ]
        ],
        "summary": "复位阀与状态位, 5Z 先回零再 4X/6X/7Y 同回零, 最后对 4 号注射泵发初始化命令并轮询至空闲."
      },
      "20": {
        "errors": {},
        "name": "A20_clean_清洗",
        "steps": [
          [
            0,
            "revoke_axis_commands"
          ],
          [
            2,
            "z5_home"
          ],
          [
            5,
            "start_6x_and_4x_to_wash"
          ],
          [
            6,
            "wait_4x_then_z5_down"
          ],
          [
            7,
            "wait_z5_6x_then_branch_mode"
          ],
          [
            10,
            "heavy_send_instr1_valve_spot_side"
          ],
          [
            20,
            "heavy_poll_idle_then_valve_needle_side"
          ],
          [
            24,
            "heavy_resend_instr1"
          ],
          [
            26,
            "heavy_poll_idle"
          ],
          [
            30,
            "heavy_send_instr2"
          ],
          [
            40,
            "heavy_poll_idle"
          ],
          [
            50,
            "heavy_cycle_count_or_finish"
          ],
          [
            60,
            "zero_count_finish"
          ],
          [
            110,
            "light_send_instr1_valve_needle_side"
          ],
          [
            120,
            "light_poll_idle_then_valve_spot_side"
          ],
          [
            130,
            "light_send_instr2"
          ],
          [
            140,
            "light_poll_idle_reset_valve_finish"
          ]
        ],
        "summary": "轴进清洗位后按 Sampling_clean_mode 分支; mode=0 重清洗按 Sampling_clean_count 循环三段泵指令, mode=1 轻清洗充液固定两段并在 entry 边界切三通."
      },
      "31": {
        "errors": {},
        "name": "A31_放板移轴",
        "steps": [
          [
            0,
            "start_7y_to_place_pos"
          ],
          [
            10,
            "wait_7y_done"
          ]
        ],
        "summary": "点样 7Y 轴移到放板位, 供上位机随后驱动机器人放板."
      },
      "32": {
        "errors": {},
        "name": "A32_放板定位",
        "steps": [],
        "summary": "置位上样定位气缸夹紧硅胶板, 同一扫描周期 DONE."
      },
      "33": {
        "errors": {},
        "name": "A33_定位松开",
        "steps": [],
        "summary": "松开上样定位气缸释放硅胶板, 同一扫描周期 DONE; 镜像 A32."
      },
      "40": {
        "errors": {},
        "name": "A40_prep_上样准备",
        "steps": [
          [
            0,
            "z5_home"
          ],
          [
            1,
            "send_prep_instr1"
          ],
          [
            2,
            "poll_idle_then_done"
          ]
        ],
        "summary": "5Z 抬到 0 后发 Sampling_prep_instructions[1] 绝对回抽蓄驱动液, /4Q 空闲即 DONE."
      },
      "50": {
        "errors": {
          "463": "P 指令解析无效 (无 P<n> 或 n<=0) 或行程越界 (真活塞位+n > 6000)",
          "464": "/4? 连续无有效帧, 重试计数 >5 (含首发共 6 次查询)"
        },
        "name": "A50_absorb_吸收液体",
        "steps": [
          [
            0,
            "z5_home"
          ],
          [
            2,
            "air_gap_send_or_skip"
          ],
          [
            3,
            "air_gap_poll_then_release_bus"
          ],
          [
            8,
            "start_xy_to_well"
          ],
          [
            10,
            "wait_xy_then_z5_down"
          ],
          [
            20,
            "wait_z5_parse_p_steps"
          ],
          [
            22,
            "acquire_bus_send_piston_query"
          ],
          [
            23,
            "parse_piston_and_stroke_check"
          ],
          [
            24,
            "requery_within_bus_hold"
          ],
          [
            25,
            "send_relative_aspirate"
          ],
          [
            30,
            "poll_idle_then_release_bus"
          ],
          [
            40,
            "z5_home_set_ok_done"
          ],
          [
            90,
            "error_lift_z5_then_report"
          ]
        ],
        "summary": "Z 回零后在空气中建气隔断, XY 到孔位下针, 解析 P 增量并以 /4? 真活塞位做 6000 步行程闸, 相对回抽后安全抬针."
      },
      "55": {
        "errors": {
          "466": "参数或指令非法 (count 越界或任一指令为空), 不可重试"
        },
        "name": "A55_润洗吹打混匀",
        "steps": [
          [
            0,
            "validate_params_z5_home_start_xy"
          ],
          [
            10,
            "wait_xy_then_z5_down"
          ],
          [
            20,
            "wait_z5_valve_needle_side"
          ],
          [
            30,
            "send_backflush_instr1"
          ],
          [
            31,
            "poll_idle"
          ],
          [
            40,
            "send_rinse_instr2"
          ],
          [
            41,
            "poll_idle"
          ],
          [
            42,
            "z5_lift_to_air"
          ],
          [
            43,
            "send_air_gap_instr3"
          ],
          [
            44,
            "poll_idle"
          ],
          [
            45,
            "z5_down_to_well"
          ],
          [
            50,
            "send_mix_instr4"
          ],
          [
            51,
            "poll_idle_cycle_loop"
          ],
          [
            60,
            "valve_off_z5_home_done"
          ]
        ],
        "summary": "回打余量→口1润洗→抬针吸气隔断→下针循环吹打; 四条泵指令一次占位串行执行, 终态活塞停在 A{gap}."
      },
      "60": {
        "errors": {},
        "name": "A60_spray_点样",
        "steps": [
          [
            0,
            "revoke_axis_commands"
          ],
          [
            1,
            "start_6x_7y_to_spot_start"
          ],
          [
            5,
            "wait_axes_send_dispense_instr1_valve_on"
          ],
          [
            10,
            "poll_idle_then_release"
          ],
          [
            15,
            "air_on_send_instr2_start_sweep_to_end"
          ],
          [
            20,
            "poll_idle_with_shuttle_subfsm"
          ],
          [
            30,
            "x6_then_7y_to_wash_pos"
          ],
          [
            40,
            "wait_7y_release_locate_done"
          ]
        ],
        "summary": "旧单次点样: 6X/7Y 到点样起点, 两段泵指令配合 6X 扫线 (泵未完时 6X 起止点往返), 收尾回清洗位并松开上样定位."
      },
      "61": {
        "errors": {},
        "name": "A61_喷涂移轴",
        "steps": [
          [
            0,
            "start_7y_to_spray_pos"
          ],
          [
            10,
            "wait_7y_done"
          ]
        ],
        "summary": "点样 7Y 轴移到点样位."
      },
      "62": {
        "errors": {
          "462": "单带程数超 60 程保险",
          "465": "/4? 并行查询连续无有效帧且重试 >5; 处置为停 6X 轴+关吹气关三通+恢复 6X 速度, 停在惰性步 99 等派发器接管"
        },
        "name": "A62_单条带点样",
        "steps": [
          [
            0,
            "init_save_velocity_move_to_start"
          ],
          [
            10,
            "wait_start_pos"
          ],
          [
            12,
            "pass_guard_acquire_bus_send_run_instr"
          ],
          [
            15,
            "start_liquid_sweep"
          ],
          [
            20,
            "wait_sweep_done"
          ],
          [
            24,
            "send_stop_start_parallel_query"
          ],
          [
            30,
            "dry_leg1_away_from_stop"
          ],
          [
            32,
            "wait_dry_leg1"
          ],
          [
            34,
            "dry_leg2_back_to_stop"
          ],
          [
            36,
            "wait_dry_leg2_cycle_loop"
          ],
          [
            38,
            "wait_query_finish_or_flip_dir"
          ],
          [
            70,
            "x6_to_wash_pos_air_on"
          ],
          [
            80,
            "wait_x6_then_7y_to_wash_pos"
          ],
          [
            90,
            "wait_7y_outputs_off_restore_velocity_done"
          ],
          [
            99,
            "error_hold_inert"
          ]
        ],
        "summary": "蛇形双向分程供液点样 (模型B E+B): 每程 A{N}R 供液扫线→到位发 /4T 停泵并并行 /4? 查活塞→吹干往复→按活塞位判终或反向续程, 最多 60 程."
      }
    },
    "gateErrors": {},
    "unknownCodeError": 101
  },
  "StagingA": {
    "actions": {
      "24": {
        "errors": {
          "103": "RUNNING 中 ActiveCode 落到 ELSE (受理与执行不一致, 正常不可达)"
        },
        "name": "A24_定位A (内联于派发器)",
        "steps": [
          [
            1,
            "accepted"
          ],
          [
            24,
            "write_output"
          ],
          [
            99,
            "done"
          ]
        ],
        "summary": "把粉末收集器定位气缸写成 StagingA_LocatorA_Target, 同扫描 DONE (不等反馈)"
      },
      "25": {
        "errors": {
          "103": "RUNNING 中 ActiveCode 落到 ELSE (受理与执行不一致, 正常不可达)"
        },
        "name": "A25_定位B (内联于派发器)",
        "steps": [
          [
            1,
            "accepted"
          ],
          [
            25,
            "write_output"
          ],
          [
            99,
            "done"
          ]
        ],
        "summary": "把溶液收集瓶定位气缸写成 StagingA_LocatorB_Target, 同扫描 DONE (不等反馈)"
      }
    },
    "gateErrors": {
      "101": "BUSY (State<>0 时又来 Start 上升沿)",
      "102": "DUPLICATE_SEQ (RequestSeq <= AcceptedSeq 或 <= CompletedSeq)",
      "190": "全局部署门 (NOT PLC_Ready 或 PLC_Deploy_State<>0), 在任何物理动作派发前拒绝",
      "402": "RESET_INTERRUPTED (RUNNING 中收到 Reset -> State 50)"
    },
    "unknownCodeError": 103
  }
})
