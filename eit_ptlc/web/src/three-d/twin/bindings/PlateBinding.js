/**
 * 功能: 把"板在哪"接到"板画在哪" —— 锚点解析、吸附换父、每帧仲裁与落位补间.
 *
 * 三层数据的落点(见 plateArbitration.js 与 PlateSlots.js 的头注释):
 *   L1 = 调度器 samples.position(权威、跨刷新、并行安全)
 *   L2 = 流程事件包络推出的亚秒过渡(只允许在 L1 认可的相邻两态之间插值)
 *   L3 = 手动直跑时的纯推断(HUD 必须标注, 权威永不升级)
 *
 * 另有一路旁证: 吸盘真空位(rob_suction, DO3)。它不参与"板在哪"的仲裁, 只回答"手上到底
 * 有没有板" —— 刷新后 L2 包络全丢、而 L1 又没有 `carried` 这个词, 全靠它把板放回手上。
 * 见 _syncSuction。
 *
 * 吸附实现是**纯换父**: 板挂到 `ACTUATOR_FLIP_SUCTION` 之下, 于是 rob_flip_suction
 * 一转, 板作为子级刚性跟随 —— 用户要的"反转吸盘板子同步跟随反转"由构造成立,
 * 不需要一行专门代码, 也不需要任何"硅胶朝上/朝下"的状态位。
 */
import * as THREE from 'three'

import { reparentPreservingWorld } from '../../anim/MachineStateDriver.js'
import { PLATE_SLOT, isMagazineSlot } from './PlateSlots.js'
import { PlateLedgerStore } from './PlateLedgerStore.js'
import { PlateTransferTracker } from './PlateTransferTracker.js'
import {
  AUTHORITY, applyLedger, applyTransfer, createPlate, recoverToSuction, resyncToLedger,
} from './plateArbitration.js'
import { bindPlateAnchors, findFlipSuctionNode, readPlateGrip } from '../scene/plates/plateAnchors.js'
import { PlateContact } from '../scene/plates/plateContact.js'
import { standardPlateGeom, suctionMountLocal } from '../scene/plates/plateGeometry.js'
import {
  bandToUv, gravityDirsWorld, machineDirsWorld, pathToUv, troughDirsWorld,
} from '../scene/plates/scrapeOverlay.js'
import {
  STAGE, SCRAPED_FALLBACK_BAND_CM, liveSpotFill, normalizeTraceFacts, spotBandRegion, wetRegion,
} from './plateTraceState.js'

/** 放板落位补间时长(秒)。放下的板要"坐正"在 CAD 位姿上, 而不是留着示教残差。 */
const SETTLE_S = 0.25

/**
 * 真空掉电后等多久才放掉"靠真空位恢复出来"的板(秒)。
 *
 * 宽限不是保守, 是必须的: 真空位走 10Hz 的 mechanism_state, 落点走 vm_node_done 事件
 * 包络, 两路谁先到没有任何保证。掉电先到就立刻销毁的话, 紧随其后的 put 会被仲裁判
 * `not_carried` 打回, 板就永远落不到台上了。
 */
const SUCTION_RELEASE_GRACE_S = 0.5

/** 板名义边长(cm)。与编译器的 SCRAPE_DEMO_PLATE_CM / plateGeometry.PLATE_NOMINAL_M 同源。 */
const PLATE_NOMINAL_CM = 20.0

const _pos = new THREE.Vector3()
const _quat = new THREE.Quaternion()

export class PlateBinding {
  /**
   * @param {object} opts
   * @param {object} opts.manifest device-manifest
   * @param {Map<string, THREE.Object3D>} opts.nodeIndex loadModel 建的节点索引
   * @param {object} opts.layer PlateFaceLayer 实例
   * @param {() => number} [opts.getMountedTool] 取当前挂载工具号
   * @param {() => boolean} [opts.getSuctionHeld] 取吸盘真空位(DO3); 见 _syncSuction
   * @param {THREE.Object3D} [opts.root] 整机根(接触判据的可碰几何来源; 不给则不做接触)
   */
  constructor({
    manifest, nodeIndex, layer, getMountedTool = () => 0, getSuctionHeld = () => false, root = null,
    getAxisMm = () => null,
  } = {}) {
    this.manifest = manifest || {}
    this.nodeIndex = nodeIndex || new Map()
    this.layer = layer
    this.ledger = new PlateLedgerStore()
    this.tracker = new PlateTransferTracker({ getMountedTool })
    this._getSuctionHeld = typeof getSuctionHeld === 'function' ? getSuctionHeld : () => false

    /** @type {Map<string, object>} plateId -> 板状态(plateArbitration 的纯对象) */
    this.plates = new Map()
    /** @type {Map<string, object>} 停放位 -> 实测几何 */
    this.anchors = new Map()
    /** @type {string[]} 解析不到的停放位(如实上报, 不用近似锚点顶替) */
    this.missing = []
    /** @type {Map<string, object>} plateId -> 落位补间 */
    this._tweens = new Map()
    /** @type {Map<string, string>} plateId -> 已应用到场景的位置(避免每帧重挂) */
    this._applied = new Map()

    this._corrections = 0
    this._rejected = 0
    this._inferredSeq = 0
    // 因"落点在 L1 覆盖外"而没被回收的板数(每帧重算): 沙盒里板进缸后就是这个状态,
    // 显示它才分得清"板留着是因为账本不知道"与"账本说它还在"
    this._uncoveredHeld = 0
    this._recoveries = 0
    /** @type {number} 真空已掉电多久(秒); 见 SUCTION_RELEASE_GRACE_S */
    this._suctionOffFor = 0
    this.suctionNode = null
    /** @type {object|null} 实时刮痕状态(见 _handleScrapeEvent); 没在刮时为 null */
    this._scrape = null
    /** 机床方向缓存(undefined=还没解过; null=解不出, 只依赖装配结构故不重试) */
    this._machineDirs = undefined

    // ── 工艺阶段痕迹(点样色带/展开润湿/废板实际刀路, 见 _updateTraces) ──
    /** 6X 活轴值(渐进色带用); 由 SceneManager 从 TwinFeed 注入 */
    this._getAxisMm = typeof getAxisMm === 'function' ? getAxisMm : () => null
    /** @type {object|null} 标称色带 region(setTraceConfig 构造, 配置未到齐前 null=留白) */
    this._spotRegion = null
    /** @type {object|null} 润湿 region(同上) */
    this._wetRegion = null
    /** @type {{xStartMm:number,xEndMm:number,yHeightMm:number}|null} 扫线示教毫米 */
    this._spotPose = null
    /** @type {object|null} spotBandCalib(渐进填充的 mm→进度换算要用) */
    this._spotCalib = null
    /** @type {((sampleId: string) => Promise<object|null>)|null} 实际刀路取数(异步注入) */
    this._traceProvider = null
    /** @type {Map<string, object>} plateId -> 痕迹 UV 缓存(按落座姿态算一次, 换座重算) */
    this._traceUv = new Map()
    /** @type {Map<string, number>} plateId -> 渐进色带的单调填充 */
    this._spotFills = new Map()
    /** @type {Map<string, {state: string, data: object|null}>} sampleId -> 实际刀路缓存 */
    this._traceFacts = new Map()
    /** 点样座机床方向缓存(6X/7Y, 与 _machineDirs 同一条 undefined/null 语义) */
    this._spotDirs = undefined

    this._bindAnchors()
    this._bindSuction()

    /** @type {PlateContact|null} 吸盘柔性接触; root 没给(单测/无场景)时为 null */
    this.contact = root
      ? new PlateContact({
        manifest: this.manifest,
        nodeIndex: this.nodeIndex,
        root,
        grip: this.plateGrip,
        excludeExtra: this._anchorNodes || [],
      })
      : null
    /** 接触判据的开关(见 plateSettings.contactEnabled) */
    this.contactEnabled = true
  }

  /**
   * 功能: 解析 13 个 CAD 板锚点(规则见 plateAnchors.bindPlateAnchors).
   * 与动作页的 PlateStage 共用同一份解析, 缸号"按 parent 名反查"那条纪律只有一处实现。
   */
  _bindAnchors() {
    const { anchors, missing, nodes } = bindPlateAnchors(this.nodeIndex)
    this.anchors = anchors
    this.missing = missing
    this._anchorNodes = nodes
  }

  /** 解析翻转气缸节点(板挂它下面就自动跟着翻)与板相对吸盘的实测刚体常量。 */
  _bindSuction() {
    this.suctionNode = findFlipSuctionNode(this.manifest, this.nodeIndex)
    this.plateGrip = readPlateGrip(this.manifest)
  }

  // ── 数据入口 ────────────────────────────────────────────────────────────

  /** 流程事件(已由 TwinFeed 配对好 args)。 */
  handleEvent(event, args) {
    this.tracker.handleEvent(event, args)
    this._handleScrapeEvent(event, args)
  }

  /**
   * 功能: 实时页的刮痕状态机 —— 把真机的分层刮取投影成板面上的凹槽.
   *
   * 三个输入, 各有各的不可替代性:
   *   · `scrape_state`(后端 cnc_path 发) —— **本次视觉解出的真实谱带**在板上的哪一块。
   *     全链只有那里知道: 下发 PLC 的是机床 mm 数组, 反算不回板帧。
   *   · `photoscrape.write_pass_z` 的 enter args.z —— 本刀切深, 用它在 pass_z_list 里
   *     定位层号(比自己拿配置做除法稳: 那份配置可能与本次运行时的不是同一版)。
   *   · `photoscrape.scrape` 的 enter/done —— 本刀的开始与结束。
   *
   * **刀内前沿刻意不插值**: 真机 A40 是一条静默的 CNC 插补, 中途没有任何进度反馈,
   * 唯一能观测的是 axis_pose 里的轴位, 而刮取段与收集段的轴位含义不同(收集时桶比刀
   * 偏 90mm), 靠它反推前沿要先猜"现在是哪一段"。宁可按刀出**离散**的三态
   * (未刮 → 整条刮松 → 整条收尽落一层), 也不画一个猜出来的前沿 —— 与 PlateStage
   * 的留白纪律同源。
   *
   * @param {object} event 事件
   * @param {object} args 已配对的入参
   * @returns {void}
   */
  _handleScrapeEvent(event, args) {
    const type = String(event?.type || '')
    if (type === 'scrape_state') {
      const band = Array.isArray(event.band_cm) ? event.band_cm.map(Number) : []
      const passes = Math.max(0, Math.round(Number(event.pass_count) || 0))
      // pass_count=0 = 本轮跳过刮板(placeholder): 清干净, 别把上一轮的坑留在新板上
      this._scrape = band.length === 4 && passes > 0
        ? {
          region: {
            frame: 'plate-cm',
            plateSizeCm: [PLATE_NOMINAL_CM, PLATE_NOMINAL_CM],
            bandCm: band,
            loosen: { axis: 'x', dir: 1 },
            clear: { axis: 'x', dir: -1 },
            passes,
          },
          passZList: (event.pass_z_list || []).map(Number),
          pass: 0,
          current: 0,
          loosen: 0,
          clear: 0,
          uv: null,
          plateId: '',
        }
        : null
      return
    }
    const scrape = this._scrape
    if (!scrape) return
    const action = String(event?.action || '')
    if (action === 'photoscrape.write_pass_z' && type === 'vm_node_enter') {
      // 层号 = 本刀 z 在 pass_z_list 里的下标 + 1。找不到(配置中途改过)就顺推一刀,
      // 总比停在上一层不动强 —— 停住的表现是"刮了半天坑不变深"。
      const z = Number(args?.z)
      const hit = scrape.passZList.findIndex((value) => Math.abs(value - z) < 1e-6)
      scrape.current = hit >= 0 ? hit + 1 : Math.min(scrape.region.passes, scrape.pass + 1)
    } else if (action === 'photoscrape.scrape' && type === 'vm_node_enter') {
      scrape.loosen = 1
      scrape.clear = 0
    } else if (action === 'photoscrape.scrape' && type === 'vm_node_done') {
      scrape.clear = 1
      scrape.pass = scrape.current || Math.min(scrape.region.passes, scrape.pass + 1)
    }
  }

  /**
   * 功能: 把刮痕状态写到刮板台上那块板(每帧, 幂等).
   *
   * UV 映射与动作页同一条纪律(PlateStage.setScrape): 板**落座在刮板台上**时算一次
   * 并缓存 —— 此刻的世界姿态就是刮取发生时的姿态; 板之后被吸走搬运, 花纹不许重投影。
   *
   * @returns {boolean} 本帧是否写了(遮罩改画布, 不算动几何, 恒返回 false 不触发阴影重渲)
   */
  _updateScrape() {
    const scrape = this._scrape
    if (!scrape || !this.layer) return false
    // 找刮板台上那块板
    let plateId = ''
    for (const plate of this.plates.values()) {
      if (plate.slot === PLATE_SLOT.SCRAPE_TABLE) { plateId = plate.plateId; break }
    }
    if (!plateId) return false
    if (scrape.plateId && scrape.plateId !== plateId) scrape.uv = null
    scrape.plateId = plateId
    const entity = this.layer.get(plateId)
    if (!entity?.root) return false
    if (!scrape.uv) {
      if (this._machineDirs === undefined) {
        this._machineDirs = machineDirsWorld(this.manifest, (name) => this._resolveScrapeNode(name))
      }
      if (!this._machineDirs) return false
      entity.root.updateWorldMatrix(true, false)
      scrape.uv = bandToUv(scrape.region, entity.root.getWorldQuaternion(_quat), this._machineDirs)
      if (!scrape.uv) return false
    }
    this.layer.applyScrape(
      plateId,
      { loosen: scrape.loosen, clear: scrape.clear, pass: scrape.pass },
      scrape.uv,
      scrape.region,
    )
    return false
  }

  /** 刮痕 UV 投影用的节点解析(先全路径, 再退叶名 —— 与 nodeIndex 的双索引约定一致)。 */
  _resolveScrapeNode(name) {
    return this.nodeIndex.get(name) || this.nodeIndex.get(String(name).split('/').pop() || '')
  }

  // ── 工艺阶段痕迹 ────────────────────────────────────────────────────────

  /**
   * 功能: 灌入痕迹标定(motion-map 的 spotBandCalib/wetFrontTargetCm + spot_pose 示教值).
   *
   * 由宿主(useTwinScene)异步取来后调用; 没到齐之前 region 为 null, 相关痕迹留白 ——
   * 与"锚点解析不到就不画"同一条纪律, 绝不用猜的映射画一条看着很真的带。
   *
   * @param {{calib?: object, pose?: object, wetFrontTargetCm?: number}} config
   * @returns {void}
   */
  setTraceConfig({ calib = null, pose = null, wetFrontTargetCm = 0 } = {}) {
    this._spotCalib = calib
    this._spotPose = pose
    this._spotRegion = spotBandRegion(calib, pose)
    this._wetRegion = wetRegion(wetFrontTargetCm, calib?.plateSizeCm)
    // 标定变了(重新示教/重标)旧映射作废, 下一帧按新 region 重算
    this._traceUv.clear()
  }

  /** 注入实际刀路取数(异步 sampleId -> /api/3d/plate-traces 响应)。 */
  setTraceProvider(provider) {
    this._traceProvider = typeof provider === 'function' ? provider : null
  }

  /**
   * 功能: 每帧把工艺阶段(空白/点样/展开/刮取)画到各板的痕迹遮罩上(幂等).
   *
   * 阶段来自调度器快照 jobs 的只读投影(PlateLedgerStore.stage); 几何一律板 cm 帧,
   * UV 映射按**当前落座**算一次并缓存(换座重算 —— cm 帧是板自身属性, 每座各自成立;
   * carried/未知座不重算, 画布维持上一座的内容)。留白纪律贯穿: 方向解不出、映射
   * 对不齐、配置未到齐, 一律不画, 绝不猜。
   * @returns {void}
   */
  _updateTraces() {
    if (!this.layer) return
    for (const plate of this.plates.values()) {
      const entry = plate.sampleId ? this.ledger.get(plate.sampleId) : null
      if (!entry) continue
      const stage = entry.stage || STAGE.BLANK
      const spotting = Boolean(entry.spottingRunning)
      if (stage === STAGE.BLANK && !spotting) continue
      const entity = this.layer.get(plate.plateId)
      if (!entity?.root) continue

      const uv = this._traceUvFor(plate, entity)
      if (!uv) continue

      // 点样色带: 段 DONE 后恒满; 点样段 RUNNING 且板在点样座时按 6X 活值渐进
      if (uv.spot) {
        let fill = stage !== STAGE.BLANK ? 1 : 0
        if (stage === STAGE.BLANK && spotting && plate.slot === PLATE_SLOT.SPOT_SEAT) {
          const axisId = this._spotRegion?.machine?.xAxis || 'axis_6x'
          fill = liveSpotFill(this._spotCalib, this._spotPose,
            this._getAxisMm(axisId), this._spotFills.get(plate.plateId) || 0)
          this._spotFills.set(plate.plateId, fill)
        } else {
          this._spotFills.delete(plate.plateId)
        }
        // 废板且视觉给出了实际谱带时, 用实际谱带矩形替代标称带(见下)
        if (!(stage === STAGE.SCRAPED && uv.factBands?.length)) {
          this.layer.applySpot(plate.plateId, [{ uv: uv.spot, fill }])
        }
      }

      // 展开润湿: 段 DONE 后前沿恒在目标高度(排液后干板上前沿界线仍可见)
      if (uv.wet && (stage === STAGE.DEVELOPED || stage === STAGE.SCRAPED)) {
        this.layer.applyWet(plate.plateId, 1, uv.wet)
      }

      // 废板: 实际刀路擦除 + 视觉检出的谱带(每块板各自的真实数据)。
      // 正在被实时刮痕状态机接管的板(_handleScrapeEvent)不叠加 —— 那边是同一份
      // 真实数据的逐刀播放, 等段 DONE 后由本分支接手终态。
      if (stage === STAGE.SCRAPED && this._scrape?.plateId !== plate.plateId) {
        const facts = this._factsFor(plate.sampleId)
        if (facts.state === 'done' && facts.data) {
          if (uv.factBands?.length) {
            // shape 显式声明成矩形: 视觉检出的斑点 bbox 近似方形, 走扫线带那套
            // "圆点滑过"的圆帽描边会把它压成胶囊、甚至溢出带外。不靠"有没有 fill"
            // 之类的隐式判据 —— 那种判据哪天给 factBands 补个字段就静默失效。
            this.layer.applySpot(plate.plateId,
              uv.factBands.map((band) => ({ uv: band, fill: 1, shape: 'rect' })))
          }
          if (uv.factPath) this.layer.applyScrapePath(plate.plateId, uv.factPath)
        } else if (facts.state === 'done' && uv.fallbackScrape) {
          // 无视觉数据(跳过拍照/历史板): 标称刮取区画刮松暖灰, **不擦除** ——
          // 擦除语义只给真实刀路, 兜底宁可保守
          this.layer.applyScrape(plate.plateId, { loosen: 1, clear: 0 },
            uv.fallbackScrape, null)
        }
      }
    }
  }

  /**
   * 功能: 一块板在当前落座下的痕迹 UV 映射(算一次缓存, 换座失效).
   *
   * 锚定按落座选(帧链见 scrapeOverlay 头注释):
   *   点样座 → machine(6X/7Y × 标定方向); 刮板台 → machine(9X/8Y);
   *   展缸 → gravity(板下沿浸槽); 其余(carried/仓)→ 不算, 画布维持原样。
   *
   * @param {object} plate 板状态(仲裁对象)
   * @param {object} entity 板实体(layer.get)
   * @returns {object|null} {spot, wet, factBands, factPath, fallbackScrape} 或 null
   */
  _traceUvFor(plate, entity) {
    const slot = plate.slot
    const cached = this._traceUv.get(plate.plateId)
    if (cached && cached.slot === slot) return cached
    const dirs = this._traceDirsFor(slot, entity)
    if (!dirs) return cached || null

    entity.root.updateWorldMatrix(true, false)
    const quat = entity.root.getWorldQuaternion(_quat)
    const out = {
      slot, spot: null, wet: null, factBands: null, factPath: null, fallbackScrape: null,
    }
    if (this._spotRegion?.bands?.length) {
      out.spot = bandToUv({
        plateSizeCm: this._spotRegion.plateSizeCm,
        bandCm: this._spotRegion.bands[0].bandCm,
        fill: this._spotRegion.bands[0].fill,
      }, quat, dirs)
    }
    if (this._wetRegion) {
      out.wet = bandToUv({
        plateSizeCm: this._wetRegion.plateSizeCm,
        bandCm: this._wetRegion.bandCm,
        fill: this._wetRegion.fill,
      }, quat, dirs)
    }
    const facts = plate.sampleId ? this._traceFacts.get(plate.sampleId) : null
    if (facts?.state === 'done' && facts.data) {
      const size = facts.data.plateSizeCm
      out.factBands = facts.data.bandsCm
        .map((box) => bandToUv({ plateSizeCm: size, bandCm: box }, quat, dirs))
        .filter(Boolean)
      if (facts.data.scrapePolylineCm.length >= 2) {
        const path = pathToUv(facts.data.scrapePolylineCm, size, quat, dirs)
        if (path) {
          out.factPath = { points: path.points, widthUv: facts.data.cutterWidthCm / (Number(size[0]) || 20) }
        }
      }
    } else {
      out.fallbackScrape = bandToUv({
        plateSizeCm: [PLATE_NOMINAL_CM, PLATE_NOMINAL_CM],
        bandCm: [...SCRAPED_FALLBACK_BAND_CM],
        loosen: { axis: 'x', dir: 1 },
        clear: { axis: 'x', dir: -1 },
      }, quat, dirs)
    }
    this._traceUv.set(plate.plateId, out)
    return out
  }

  /** 落座 -> cm 轴锚定方向(解不出 null=留白; 见 _traceUvFor 的注释)。 */
  _traceDirsFor(slot, entity) {
    if (slot === PLATE_SLOT.SPOT_SEAT) {
      if (this._spotDirs === undefined) {
        const machine = this._spotRegion?.machine || {}
        this._spotDirs = machineDirsWorld(this.manifest, (name) => this._resolveScrapeNode(name), {
          xAxis: machine.xAxis || 'axis_6x',
          yAxis: machine.yAxis || 'axis_7y',
          xDir: machine.xDir ?? 1,
          yDir: machine.yDir ?? 1,
        })
      }
      return this._spotDirs
    }
    if (slot === PLATE_SLOT.SCRAPE_TABLE) {
      if (this._machineDirs === undefined) {
        this._machineDirs = machineDirsWorld(this.manifest, (name) => this._resolveScrapeNode(name))
      }
      return this._machineDirs
    }
    const match = /^tank:(\d+)$/.exec(String(slot || ''))
    if (match) {
      entity.root.updateWorldMatrix(true, false)
      const quat = entity.root.getWorldQuaternion(_quat)
      const silicaUp = entity.geom?.silicaUp !== false
      // 竖插缸走重力锚定; 本机的卧式缸(板平躺)退到槽向锚定(与 PlateStage._troughDirs 同构)
      const gravity = gravityDirsWorld(quat, silicaUp)
      if (gravity) return gravity
      const spec = (this.manifest?.tanks || []).find((tank) => tank.id === `tank${match[1]}`)
      const path = String(spec?.liquidNode || '')
      const node = this._resolveScrapeNode(path)
      if (!node) return null
      node.updateWorldMatrix(true, false)
      return troughDirsWorld(
        quat,
        entity.root.getWorldPosition(_pos),
        node.getWorldPosition(new THREE.Vector3()),
        silicaUp,
      )
    }
    return null
  }

  /**
   * 某样品的实际刀路缓存(首访触发一次异步取数; 失败按"无数据"处理不重试 ——
   * 刷新页面即重试, 比在每帧循环里退避重试简单得多)。
   */
  _factsFor(sampleId) {
    const key = String(sampleId || '')
    let facts = this._traceFacts.get(key)
    if (!facts) {
      facts = { state: this._traceProvider ? 'loading' : 'done', data: null }
      this._traceFacts.set(key, facts)
      if (this._traceProvider) {
        Promise.resolve(this._traceProvider(key))
          .then((raw) => {
            facts.state = 'done'
            facts.data = normalizeTraceFacts(raw)
            // 实际数据到了, 该板的 UV 缓存要重算(factBands/factPath 是缓存的一部分)
            this._traceUv.delete(`sample:${key}`)
          })
          .catch(() => { facts.state = 'done' })
      }
    }
    return facts
  }

  /** 调度器快照。 */
  pushLedger(snapshot, nowMs = Date.now()) {
    return this.ledger.push(snapshot, nowMs)
  }

  /** 断流: 冻结账本、丢弃在途的末点推断。 */
  markDisconnected() {
    this.ledger.markDisconnected()
    this.tracker.reset()
  }

  /**
   * 功能: 向后 seek 的清场 —— 把板面痕迹与全部落位记忆一并归零.
   *
   * 为什么 markDisconnected() 不够: 它只清账本与搬运推断, **不碰板面**。而点样色带、
   * 润湿、刮痕这三层是单调累加的(_spotFills 是"单调填充", 刮痕遮罩按前沿只增不减),
   * 断流冻结时保留它们是对的 —— 断线又不会把粉擦掉。但回放跳回过去时它们必须消失,
   * 否则会看到一块"还没点样却已经有色带"的板, 而且没有任何报错。
   *
   * 擦除的做法是 release 掉全部在场板: 板池复用时 release 已经负责还原共享材质与
   * 收回残余薄板 —— 这条路是本文件与 PlateStage 既有的 seek 契约, 不是新造的。
   *
   * @returns {void}
   */
  resetForSeek() {
    this.markDisconnected()
    for (const plateId of this.layer?.plateIds?.() || []) {
      this.layer.release(plateId)
    }
    this._tweens.clear()
    // _applied 是"已写进场景的位置"的记忆, 不清的话关键帧改了板位却**静默不重绘**
    this._applied.clear()
    this._traceUv.clear()
    this._spotFills.clear()
    // 实际刀路是按 sampleId 缓存的异步取数结果; 回放跳到别的批次必须重取,
    // 否则会把上一个样品的刀路画到这一个上。
    this._traceFacts.clear()
    this._scrape = null
    this._suctionOffFor = 0
    this._uncoveredHeld = 0
  }

  /**
   * 功能: 料仓堆叠透传给实体层.
   * @param {string} magazineId 'feed' | 'waste'
   * @param {number} count 张数(来自 material_state)
   * @param {number} pitchM 现场实测节距(米), 未标定给 0
   * @param {THREE.Object3D|null} carriageNode 升降滑车; 给了板堆就随 1Z/2Z 升降
   */
  setMagazine(magazineId, count, pitchM = 0, carriageNode = null) {
    const slot = magazineId === 'waste' ? PLATE_SLOT.WASTE : PLATE_SLOT.FEEDLIFT
    const geom = this.anchors.get(slot)
    if (!geom || !this.layer) return false
    return this.layer.setMagazine(magazineId, {
      geom,
      parent: carriageNode || geom.parent,
      count,
      pitchM,
    })
  }

  // ── 每帧 ────────────────────────────────────────────────────────────────

  /**
   * 功能: 每帧推进. 顺序固定: 重同步 → 对齐账本 → 消费 L2 迁移 → 对齐真空位 → 写场景 → 走补间.
   *
   * 真空位排在 L2 之后: 正常取放由包络说了算, 真空位只补它没覆盖到的洞(主要是刷新)。
   * @param {number} delta 帧间隔(秒)
   * @returns {boolean} 本帧是否动过场景(供调用方决定要不要重渲阴影)
   */
  update(delta = 0) {
    let moved = false
    if (this.ledger.consumeResync()) moved = this._resyncAll() || moved
    moved = this._syncLedger() || moved
    moved = this._applyTransfers() || moved
    moved = this._syncSuction(delta) || moved
    moved = this._writeScene() || moved
    moved = this._stepTweens(delta) || moved
    this._updateScrape()
    this._updateTraces()
    // ⚠ 必须在 _writeScene 之外: 那里开头的 `_applied` 短路会跳过"落点没变"的板,
    // 而接触修正恰恰要在板不换落点的每一帧都重算(机械臂在动, 穿透量每帧都不同)。
    moved = this._resolveContact() || moved
    return moved
  }

  /**
   * 功能: 每帧的吸盘柔性接触 —— 持板顶到硬表面时吸盘压缩, 而不是把板顶进去.
   *
   * 与 PlateStage.update 同构(共用 plateContact), 差别只在"哪块板在手上"的来源:
   * 这边是仲裁后的账本状态, 那边是片段的 `plate` 原语。
   *
   * 每帧先回到自由位姿再修 —— 不在上一帧结果上累加, 否则板会一路往回缩。
   * @returns {boolean} 本帧是否动过场景
   */
  _resolveContact() {
    if (!this.contact) return false
    // 功能关掉/没有吸盘节点: 彻底复位
    if (!this.contactEnabled || !this.suctionNode) {
      this.contact.releaseCups()
      return false
    }
    const carried = [...this.plates.values()].find((plate) => plate.slot === PLATE_SLOT.CARRIED)
    const entity = carried ? this.layer?.get(carried.plateId) : null
    if (!entity) {
      // 手上没板时的渐进回弹, 与 PlateStage.update 同一条规则(共用 plateContact)
      this.contact.relaxOnPlates(this._seatedPlates(), this.layer?.silicaMm)
      return true
    }
    const mount = suctionMountLocal(this.plateGrip, entity.geom, this.layer.silicaMm)
    if (mount) {
      this.suctionNode.add(entity.root)
      entity.root.position.copy(mount.position)
      entity.root.quaternion.copy(mount.quaternion)
      entity.root.updateMatrix()
    }
    this.contact.resolve(entity.root, entity.geom, this.layer.silicaMm)
    return true
  }

  /**
   * 功能: 当前**已落座**的板(不含手上那块) —— 断吸后求渐进回弹的约束面.
   * @returns {Array<{root: object, geom: object}>}
   */
  _seatedPlates() {
    const out = []
    for (const plate of this.plates.values()) {
      if (plate.slot === PLATE_SLOT.CARRIED) continue
      const entity = this.layer?.get(plate.plateId)
      if (entity?.root && entity?.geom) out.push(entity)
    }
    return out
  }

  /** 开关接触判据; 关掉时立刻把吸盘复位, 不留一个压扁的吸盘在画面上。 */
  setContactEnabled(enabled) {
    this.contactEnabled = Boolean(enabled)
    if (!this.contactEnabled) this.contact?.releaseCups()
  }

  /** 后端重启/重连: 全部板按 L1 归位, 清掉 L2 的推断痕迹。 */
  _resyncAll() {
    for (const entry of this.ledger.plates()) {
      const plate = this.plates.get(`sample:${entry.sampleId}`)
      if (plate) this.plates.set(plate.plateId, resyncToLedger(plate, entry.position))
    }
    this.tracker.reset()
    return true
  }

  /** 建/销板实例, 并把 L1 位置过一遍仲裁。 */
  _syncLedger() {
    const seen = new Set()
    let moved = false
    this._uncoveredHeld = 0

    for (const entry of this.ledger.plates()) {
      const plateId = `sample:${entry.sampleId}`
      seen.add(plateId)
      let plate = this.plates.get(plateId)
      if (!plate) {
        plate = createPlate({
          plateId,
          sampleId: entry.sampleId,
          slot: entry.position,
          authority: AUTHORITY.L1,
        })
        this.plates.set(plateId, plate)
        moved = true
        continue
      }
      const { plate: next, outcome } = applyLedger(plate, entry.position)
      if (outcome === 'corrected') this._corrections += 1
      if (next !== plate) {
        this.plates.set(plateId, next)
        if (outcome === 'corrected') moved = true
      }
    }

    // L1 里已经没有的样品(跑完进废板仓 / 被清批)→ 回收板实例
    for (const plateId of [...this.plates.keys()]) {
      if (seen.has(plateId)) continue
      const plate = this.plates.get(plateId)
      if (plate?.authority === AUTHORITY.L3) continue   // 推断板不由账本回收
      // "不在 plates() 里"有两种成因, 不能一并当成消失: 样品真的离开了账本(该回收), 与
      // 样品还在、只是位置是仓态(onPlate=false, 仓态由料仓堆叠画)。板正被吸盘拿在手上
      // 而账本记着仓态, 恰恰是从上料仓吸起后最常见的一帧 —— 这时回收就等于板在半空蒸发。
      if (plate?.slot === PLATE_SLOT.CARRIED && this.ledger.get(plate.sampleId)) continue
      // 板停在 L1 覆盖不到的落点上: "账本没提它"是**不知道**, 不是**没有**。
      // 沙盒不装调度器, 缸里有哪块板它真不知道; 把这种情况当成"消失"会让板在缸里
      // 凭空蒸发且无任何线索。live 的调度器快照没有 coverage 字段 -> covers() 恒 true,
      // 这一条永不触发, 回收规则逐字不变。
      if (!this.ledger.covers(plate?.slot)) { this._uncoveredHeld += 1; continue }
      this._dropPlate(plateId)
      moved = true
    }
    return moved
  }

  /** 消费 L2 迁移意图, 过仲裁闸门。 */
  _applyTransfers() {
    let moved = false
    for (const transfer of this.tracker.consumeTransfers()) {
      const plateId = this._plateIdForRun(transfer)
      const plate = this.plates.get(plateId)
      if (!plate) continue
      const { plate: next, accepted } = applyTransfer(plate, transfer)
      if (!accepted) {
        this._rejected += 1
        continue
      }
      this.plates.set(plateId, next)
      moved = true
    }
    return moved
  }

  /**
   * 由 run_id 定位板。归属不到时**不猜**: 落到一块 L3 推断板上并如实标注, 绝不
   * 硬塞给某个已知样品 —— 那会让画面看起来更"完整", 代价是彻底错的归属。
   */
  _plateIdForRun(transfer) {
    const sampleId = this.ledger.sampleIdForRun(transfer.runId)
    if (sampleId) return `sample:${sampleId}`

    // L1 身份是投影合成的(压根没有 run 索引)时, 归属只能靠"板此刻在哪"。
    //
    // 门控在 syntheticIdentity() 而不是无条件, 因为两种"空串"含义不同:
    //   live 页空串 = "这是一次手动直跑, 确实无归属" —— 那是事实, 不该被落点顺手认领;
    //   仿真页空串 = "投影根本没有 run 索引" —— 是两回事。
    // 判据与 applyTransfer 的两道闸门逐字相同: pick 要求"板确实在那个落点上",
    // put 要求"板确实在手上"(not_carried 闸)。恰好一块时这不是猜; 0 块或 >=2 块
    // 一律退回 L3 推断板, 一个字都不硬挑。
    if (this.ledger.syntheticIdentity()) {
      const wanted = transfer.kind === 'pick' ? transfer.slot : PLATE_SLOT.CARRIED
      const at = [...this.plates.values()].filter((plate) => plate.slot === wanted)
      if (at.length === 1) return at[0].plateId
    }

    // 手动直跑: 全局只维持一块推断板, 免得每次单发动作都长出一块新的
    for (const [plateId, plate] of this.plates.entries()) {
      if (plate.authority === AUTHORITY.L3) return plateId
    }
    this._inferredSeq += 1
    const plateId = `inferred:${this._inferredSeq}`
    this.plates.set(plateId, createPlate({
      plateId,
      slot: transfer.kind === 'pick' ? transfer.slot : PLATE_SLOT.CARRIED,
      authority: AUTHORITY.L3,
    }))
    return plateId
  }

  /**
   * 功能: 每帧对齐吸盘真空位与"画面上有没有板在手上" —— 刷新后能看见板全靠这一步.
   *
   * 为什么需要它: `carried` 是三维派生的第五个位置词, 后端 samples.position 里没有,
   * L2 包络又刷新即丢。于是刷新后板要么瞬移回上一个停放位, 要么(上一位是料仓时)一块
   * 都不画 —— 后者就是"板凭空消失"。真空位 DO3 是唯一跨刷新还在的证据, 后端为此专门
   * 发布了 rob_suction 这个无几何的纯状态机构(robot_controller.py:63-66)。
   *
   * @param {number} delta 帧间隔(秒)
   * @returns {boolean} 本帧是否动过板状态
   */
  _syncSuction(delta = 0) {
    const held = Boolean(this._getSuctionHeld())
    const carried = [...this.plates.values()].find((plate) => plate.slot === PLATE_SLOT.CARRIED)

    if (held) {
      this._suctionOffFor = 0
      return carried ? this._promoteRecoveredPlate(carried) : this._recoverCarriedPlate()
    }

    // 真空掉电。正常取放由 L2 的 put 落位, 这里只收拾**自己恢复出来**的那块板 ——
    // 去动别人的板就成了第二套仲裁。
    if (!carried?.recovered) {
      this._suctionOffFor = 0
      return false
    }
    this._suctionOffFor += Math.max(0, delta)
    if (this._suctionOffFor < SUCTION_RELEASE_GRACE_S) return false
    this._suctionOffFor = 0
    return this._releaseRecoveredPlate(carried)
  }

  /**
   * 功能: 真空说手上有板而画面上没有 —— 补一块.
   *
   * 归属规则与 _plateIdForRun 同源: 能确定就归属, 不能确定就如实标成推断板,
   * **绝不硬挑一个样品**。机器人只有一台, 所以"恰好一个样品有 RUNNING 作业"时
   * 那就是它, 这是调度器自己声明的在制品, 不是猜。
   * @returns {boolean} 是否动过板状态
   */
  _recoverCarriedPlate() {
    const candidates = this.ledger.runningSamples()
    if (candidates.length === 1) {
      const entry = candidates[0]
      const plateId = `sample:${entry.sampleId}`
      // 仓态样品 _syncLedger 没建过对象(板在仓里由堆叠承担), 按需补一个
      const plate = this.plates.get(plateId) || createPlate({
        plateId,
        sampleId: entry.sampleId,
        slot: entry.position,
        authority: AUTHORITY.L1,
      })
      // 把来处塞进 _applied: _writeScene 拿它当尺寸与硅胶朝向的提示("上一次画在哪,
      // 那就是这块板的来处")。刷新后这张表是空的, 不补的话从料仓取的板会被画成硅胶朝上。
      if (entry.position && !this._applied.has(plateId)) this._applied.set(plateId, entry.position)
      this.plates.set(plateId, recoverToSuction(plate, entry.position))
      this._recoveries += 1
      return true
    }

    // 归属不到(手动直跑, 或多条作业同时在跑): 全局只维持一块推断板, 与 _plateIdForRun 同款
    for (const [plateId, plate] of this.plates.entries()) {
      if (plate.authority !== AUTHORITY.L3) continue
      this.plates.set(plateId, recoverToSuction(plate, plate.slot))
      this._recoveries += 1
      return true
    }
    this._inferredSeq += 1
    const plateId = `inferred:${this._inferredSeq}`
    this.plates.set(plateId, recoverToSuction(createPlate({ plateId, authority: AUTHORITY.L3 })))
    this._recoveries += 1
    return true
  }

  /**
   * 功能: 恢复出来的**无归属**板, 一旦账本到齐就认领到正确的样品上.
   *
   * 刷新时真空位(WS 10Hz)与调度器快照(3s 轮询)谁先到没有保证。真空先到时只能先画一块
   * 无归属的推断板; 快照随后到达就**必须**把它认领掉 —— 否则账本会照常另建一块正常的板,
   * 画面上成了"手上一块 + 台上一块"的双份板, 而那正是最难归因的一类错。
   *
   * 只认领自己恢复出来的 L3 板: 由 L2 包络正常取起来、只是归属不到 run 的推断板
   * (recovered=false)不在此列 —— 那种归属不到是事实, 不该被账本顺手领走。
   * @param {object} carried 当前在手上的板
   * @returns {boolean} 是否动过板状态
   */
  _promoteRecoveredPlate(carried) {
    if (!carried.recovered || carried.authority !== AUTHORITY.L3) return false
    if (this.ledger.runningSamples().length !== 1) return false
    this._dropPlate(carried.plateId)
    return this._recoverCarriedPlate()
  }

  /**
   * 功能: 真空掉电且过了宽限仍没有 L2 落点来接手 —— 收掉恢复出来的板.
   *
   * L3 的板没有任何账本背书: 真空一断就再没有证据说它存在, 如实销毁, 而不是留一块
   * 悬在吸盘上的板。有账本背书的交还 L1, 由账本说它在哪。
   * @param {object} plate 板状态
   * @returns {boolean} 是否动过板状态
   */
  _releaseRecoveredPlate(plate) {
    const entry = plate.authority === AUTHORITY.L3 ? null : this.ledger.get(plate.sampleId)
    if (!entry?.position) {
      this._dropPlate(plate.plateId)
      return true
    }
    this.plates.set(plate.plateId, resyncToLedger(plate, entry.position))
    return true
  }

  /** 回收一块板实例(状态、场景实体、在途补间与痕迹缓存一起清干净)。 */
  _dropPlate(plateId) {
    this.plates.delete(plateId)
    this.layer?.release(plateId)
    this._applied.delete(plateId)
    this._tweens.delete(plateId)
    this._traceUv.delete(plateId)
    this._spotFills.delete(plateId)
  }

  /** 把板状态写进场景: 挂吸盘 / 摆到锚点 / 仓态不画。 */
  _writeScene() {
    let moved = false
    for (const [plateId, plate] of this.plates.entries()) {
      const slot = plate.slot
      if (this._applied.get(plateId) === slot) continue

      if (!slot || isMagazineSlot(slot)) {
        // 仓态由料仓堆叠承担, 建独立实例会与 material_state 的张数双记账
        this.layer?.release(plateId)
        this._applied.set(plateId, slot)
        this._tweens.delete(plateId)
        moved = true
        continue
      }

      if (slot === PLATE_SLOT.CARRIED) {
        // 上一次画在哪, 那就是这块板的来处 —— 拿它定尺寸与硅胶朝向。板池是复用的,
        // 不给这个提示时会沿用上一块板的朝向(从料仓取的板可能被画成硅胶朝上, 而那在
        // 画面上看不出错: 等于吸盘去吸粉面)。
        if (this._attachToSuction(plateId, this._applied.get(plateId) || '')) {
          this._applied.set(plateId, slot)
          this._tweens.delete(plateId)
          moved = true
        }
        continue
      }

      if (this._dropToSlot(plateId, slot)) {
        this._applied.set(plateId, slot)
        moved = true
      }
    }
    return moved
  }

  /**
   * 吸附: 按**吸盘自己的几何**把板钉到翻转节点下的刀具位姿。
   *
   * 之后 rob_flip_suction 每帧被驱动时, 板作为子级自然被扫过 180°, 姿态与角速度与吸盘
   * 完全一致 —— 这一条与实现无关, 由父子关系构造成立。
   *
   * 为什么不再用"保世界位姿换父": 那会把取板那一刻板与吸盘的**错位**一并保留下来。
   * 实时页的错位来源比片段页还多(账本迟到、L2 包络推断、断流重连), 保下来只是把错误
   * 冻得更牢。刀具常量与板从哪来无关, 摆出来永远贴合。读不到常量时才退回旧路径。
   *
   * @param {string} plateId 板号
   * @param {string} [slot] 板来自/去往的落点(定尺寸与硅胶朝向; 板池复用, 不给会沿用上一块的)
   * @returns {boolean} 是否生效
   */
  _attachToSuction(plateId, slot = '') {
    if (!this.suctionNode || !this.layer) return false
    const plate = this.layer.get(plateId) || this.layer.acquire(plateId)
    const hint = slot ? this.anchors.get(slot) : null
    if (hint) this.layer.setGeom(plateId, hint)

    const grip = suctionMountLocal(
      this.plateGrip,
      plate.geom || standardPlateGeom(),
      this.layer.silicaMm,
    )
    if (grip) {
      this.suctionNode.add(plate.root)
      plate.root.position.copy(grip.position)
      plate.root.quaternion.copy(grip.quaternion)
      plate.root.updateMatrix()
      plate.root.updateMatrixWorld(true)
      return true
    }

    if (!plate?.root.parent) {
      // 首次就在手上(刷新后恢复)且没有刀具常量: 没有可保的世界位姿, 直接挂上
      this.suctionNode.add(plate.root)
      plate.root.position.set(0, 0, 0)
      plate.root.quaternion.identity()
      return true
    }
    return reparentPreservingWorld(plate.root, this.suctionNode)
  }

  /**
   * 放板: 先保世界位姿换父(画面连续), 再用短补间"坐正"到 CAD 锚点位姿。
   * 不保留示教残差 —— 放下的板应当落在设计位置上。
   */
  _dropToSlot(plateId, slot) {
    const geom = this.anchors.get(slot)
    if (!geom?.parent || !this.layer) return false

    const entity = this.layer.get(plateId)
    const hadPose = Boolean(entity?.root.parent)
    this.layer.place(plateId, geom)      // 换父 + 按实测尺寸铺两层
    const root = this.layer.get(plateId).root

    if (!hadPose) return true            // 没有起始位姿可插值, 直接就位

    this._tweens.set(plateId, {
      t: 0,
      fromPos: _pos.copy(root.position).clone(),
      fromQuat: _quat.copy(root.quaternion).clone(),
      toPos: geom.position.clone(),
      toQuat: geom.quaternion.clone(),
    })
    return true
  }

  /** 推进落位补间。 */
  _stepTweens(delta) {
    if (!this._tweens.size || !(delta > 0)) return false
    let moved = false
    for (const [plateId, tween] of [...this._tweens.entries()]) {
      const entity = this.layer?.get(plateId)
      if (!entity) {
        this._tweens.delete(plateId)
        continue
      }
      tween.t = Math.min(1, tween.t + delta / SETTLE_S)
      const k = 1 - (1 - tween.t) ** 3          // ease-out cubic
      entity.root.position.lerpVectors(tween.fromPos, tween.toPos, k)
      entity.root.quaternion.slerpQuaternions(tween.fromQuat, tween.toQuat, k)
      moved = true
      if (tween.t >= 1) this._tweens.delete(plateId)
    }
    return moved
  }

  // ── 诊断 ────────────────────────────────────────────────────────────────

  /** 供 HUD 的只读状态。 */
  status(nowMs = Date.now()) {
    const ledger = this.ledger.status(nowMs)
    return {
      ...ledger,
      anchors: this.anchors.size,
      missingAnchors: [...this.missing],
      suctionBound: Boolean(this.suctionNode),
      contactEnabled: this.contactEnabled,
      contactReady: Boolean(this.contact?.ready),
      contact: this.contact?.last || null,
      corrections: this._corrections,
      rejected: this._rejected,
      uncoveredHeld: this._uncoveredHeld,
      coveredSlots: this.ledger.coveredSlots() ? [...this.ledger.coveredSlots()] : null,
      syntheticIdentity: this.ledger.syntheticIdentity(),
      suctionHeld: Boolean(this._getSuctionHeld()),
      recoveries: this._recoveries,
      transfer: this.tracker.status(),
      rows: [...this.plates.values()].map((plate) => ({
        plateId: plate.plateId,
        sampleId: plate.sampleId,
        slot: plate.slot,
        authority: plate.authority,
        suspect: plate.suspect,
        // 靠真空位恢复出来的板: 有 DO 背书、但落点(以及无归属时的归属)是补出来的,
        // 与包络取起来的板不是一回事, 诊断时必须分得开。
        recovered: plate.recovered,
      })),
    }
  }

  dispose() {
    this.plates.clear()
    this.anchors.clear()
    this._tweens.clear()
    this._applied.clear()
    this._suctionOffFor = 0
    this.tracker.reset()
    // 吸盘要自己复位: 驱动层 home() 不管 ACTUATOR_FLIP_SUCTION 的孙节点
    this.contact?.dispose()
    this.contact = null
  }
}
