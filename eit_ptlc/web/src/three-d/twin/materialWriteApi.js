/**
 * 功能: 三维页发起的物料账本写通道 —— 全部动词封装到**既有** REST 端点.
 *
 * 协议边界 (PTLC_REALTIME_PROTOCOL.md §5.1): 三维不新增任何私有写端点, 写入一律走
 * 上位机既有的 /api/materials/* 人工盘点端点; 写后**不做乐观渲染**, 画面变化只来自
 * 下一帧 material_state 推流 (单向闭环)。
 *
 * base 可注入: 实时页缺省 /api/materials, 仿真页传 /api/sim/materials (沙盒端点由
 * 阶段③里程碑提供, 未就绪时 404 由调用方按"沙盒物料端点未就绪"报出, 前端不因此阻塞)。
 * request 可注入替身供 node --test 断言 动词 -> URL/body 的映射。
 */
import { requestJson } from '../../api.js'

/**
 * 功能: 构造一套物料写动词.
 * @param {object} [options] 参数对象
 * @param {string} [options.base='/api/materials'] 端点前缀
 * @param {Function} [options.request] (path, body) => Promise; 缺省 = 宿主 requestJson
 * @returns {object} 动词集合
 */
export function createMaterialWriteApi({ base = '/api/materials', request = requestJson } = {}) {
  return {
    /** 孔位/整板 置新旧: hole 省略 = 整板 */
    mark({ kind, plate, hole = null, state }) {
      const body = { kind, plate, state }
      if (hole != null) body.hole = hole
      return request(`${base}/mark`, body)
    },
    /** 单件内容物 (粉 mm³ / 液 mL / 已淋洗); 缺省字段不动 */
    setCellAmount({ kind, plate, hole, ...fields }) {
      return request(`${base}/cell_amount`, { kind, plate, hole, ...fields })
    },
    /** 中转区板号 (null = 置空) */
    setStaging(area, plate) {
      return request(`${base}/staging`, { area, plate })
    },
    /** 货架库位在架 */
    setRack(kind, plate, present) {
      return request(`${base}/rack`, { kind, plate, present })
    },
    /** 玻璃板仓张数 */
    setMagazine(magazine, count) {
      return request(`${base}/magazine`, { magazine, count })
    },
    /** 溶剂瓶余量 mL */
    setBottle(bottle, volumeMl) {
      return request(`${base}/bottle`, { bottle, volume_ml: volumeMl })
    },
    /** 单板停放位有板/无板 */
    setSeat(seat, present) {
      return request(`${base}/seat`, { seat, present })
    },
    /** 板位上那块板的工艺阶段 (blank/spotted/developed/scraped); 空座会被后端拒 */
    setSeatStage(seat, stage) {
      return request(`${base}/seat`, { seat, stage })
    },
    /** 清夹爪在途 (landAt: '' 只清行 | rack | staging) */
    clearTransit(carrier, landAt = '') {
      return request(`${base}/transit`, { carrier, land_at: landAt })
    },
    /** 清工位座上的单件 (去向不猜) */
    clearPayloadSeat(seat) {
      return request(`${base}/payload_seat`, { seat })
    },
  }
}

/** 实时页缺省实例 (SimView 用 createMaterialWriteApi({ base: '/api/sim/materials' })) */
export const liveMaterialWriteApi = createMaterialWriteApi()
