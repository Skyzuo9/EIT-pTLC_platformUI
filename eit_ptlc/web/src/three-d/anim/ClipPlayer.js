/**
 * 功能: 片段播放器 —— 时钟与传输控制(play/pause/seek/speed/loop), 驱动 MachineRig.
 *
 * seek 语义(动画引擎最容易做错的地方):
 *   连续通道(轴/关节)求值是纯函数, 任意 t 直接算; 但 attach/highlight 是**有状态的
 *   离散事件**. 处理办法: 向前推进时只补放 (prevT, t] 里的事件; **向后**跳则
 *   rig.home() 清场后重放 [0, t] 的全部事件 —— 事件个位数, 重放开销可忽略,
 *   换来的是"拖到哪儿都对"的确定性.
 *
 * 镜头事件只在**自然播放**跨过时触发(seek 不触发): 拖进度条时镜头乱飞非常晕,
 * 而镜头不参与机器状态, 跳过不影响正确性.
 */
import { evaluateChannels, eventsUpTo, stepIndexAt } from './clipSchema.js'

export class ClipPlayer {
  /**
   * 功能: 建播放器.
   * @param {object} options 参数
   * @param {import('./MachineRig.js').MachineRig} options.rig 机器装配
   * @param {import('../twin/scene/CameraRig.js').CameraRig} [options.cameraRig] 相机(镜头事件用)
   * @param {object} [options.manifest] manifest(镜头 station 机位查询)
   * @param {(state: object) => void} [options.onChange] 状态回调(供 UI)
   */
  constructor({ rig, cameraRig, manifest, onChange }) {
    this.rig = rig
    this.cameraRig = cameraRig
    this.manifest = manifest
    this.onChange = onChange

    this.clip = null
    this.time = 0
    this.playing = false
    this.speed = 1
    this.loop = false
    /** 已生效的事件数(单调前进时的游标) */
    this._applied = 0
    /** 不能用 _applied===0 代替：第一个离散事件之前，0 本身是正常游标。 */
    this._initialized = false
  }

  /**
   * 功能: 装载一个编译好的片段并回到起点.
   * @param {object} compiled compileClip 产物
   * @returns {void}
   */
  load(compiled) {
    this.clip = compiled
    this.playing = false
    this._initialized = false
    this.seek(0)
  }

  /**
   * 功能: 播放/暂停.
   * @returns {boolean} 播放态
   */
  toggle() {
    if (!this.clip) return false
    // 播完了再按播放 = 从头再来
    if (!this.playing && this.time >= this.clip.duration - 1e-6) this.seek(0)
    this.playing = !this.playing
    this._notify()
    return this.playing
  }

  /**
   * 功能: 设播放倍速.
   * @param {number} speed 倍速(0.25~4)
   * @returns {void}
   */
  setSpeed(speed) {
    this.speed = Math.min(4, Math.max(0.25, Number(speed) || 1))
    this._notify()
  }

  /**
   * 功能: 跳到指定时刻(秒). 向后跳走"回家重放", 保证确定性.
   * @param {number} t 目标时刻
   * @param {boolean} [fireCamera=false] 是否触发跨过的镜头事件(自然播放才为 true)
   * @returns {void}
   */
  seek(t, fireCamera = false) {
    if (!this.clip) return
    const target = Math.min(Math.max(0, t), this.clip.duration)

    if (target < this.time - 1e-9 || !this._initialized) {
      // 回家重放: 每个离散事件先恢复到它发生时的连续姿态，再触发事件。
      // 工具锁紧会读取当时的 TOOL_MOUNT 世界变换；若先锁紧、最后才写关节，
      // 就会在 Home 姿态下建立错误约束，随后瞬间跳转几十甚至上百度。
      this.rig.home()
      this._applied = 0
      const due = eventsUpTo(this.clip, target)
      for (const event of due) {
        this._applyContinuous(event.t)
        this._fire(event, false)
      }
      this._applied = due.length
    } else {
      // 单调前进: 只补放 (time, target] 的事件
      const events = this.clip.events
      while (this._applied < events.length && events[this._applied].t <= target + 1e-9) {
        const event = events[this._applied]
        this._applyContinuous(event.t)
        this._fire(event, fireCamera)
        this._applied += 1
      }
    }

    this.time = target
    this._applyContinuous(target)
    this._initialized = true
    this._notify()
  }

  /**
   * 功能: 帧推进 —— 挂到 SceneManager.addFrameHook.
   * @param {number} delta 距上一帧秒数
   * @returns {void}
   */
  tick(delta) {
    if (!this.playing || !this.clip) return
    // 主轴相位: 唯一按 dt 累加而非按 t 求值的量(转角是无限增长量, 见 clipSchema 的
    // spindle 原语注释)。乘倍速, 这样 2× 播放时刀也转得快一倍, 与轴运动同步。
    this.rig.updateSpindles?.(delta * this.speed)
    const next = this.time + delta * this.speed
    if (next >= this.clip.duration) {
      this.seek(this.clip.duration, true)
      if (this.loop) {
        this.seek(0)
      } else {
        this.playing = false
        this._notify()
      }
      return
    }
    this.seek(next, true)
  }

  /**
   * 功能: 把连续通道的值写进装配.
   * @param {number} t 时刻
   * @returns {void}
   */
  _applyContinuous(t) {
    const state = evaluateChannels(this.clip, t)
    for (const [id, mm] of Object.entries(state.axes)) this.rig.setAxisMm(id, mm)
    if (this.rig.joints.length) this.rig.setJointsDeg(state.joints)
    for (const [id, offset] of Object.entries(state.nodes)) this.rig.setNodeOffset(id, offset)
    for (const [id, value] of Object.entries(state.actuators)) this.rig.setActuator(id, value)
    for (const [id, value] of Object.entries(state.linkages)) this.rig.setLinkage(id, value)
    // 工艺灯与轴同属连续通道: 亮度是 t 的纯函数, 拖进度条到哪儿都算得出, 不需要重放
    for (const [id, value] of Object.entries(state.lights || {})) this.rig.setLight?.(id, value)
    // 展缸液面同理, 值是毫升(换算与封顶在 setLiquidMl 里做)
    for (const [id, ml] of Object.entries(state.liquids || {})) this.rig.setLiquidMl?.(id, ml)
    // 注射泵同理: 主通道毫升(柱塞/液柱/丝杆一体), 阀位通道端口号(角度换算在写入层)
    for (const [id, ml] of Object.entries(state.pumps || {})) this.rig.setPumpMl?.(id, ml)
    for (const [id, port] of Object.entries(state.pumpPorts || {})) this.rig.setPumpValvePort?.(id, port)
    // 刮取前沿同理: loosen/clear 是 t 的纯函数, 拖进度条随处可算。条带矩形是编译器
    // 算好的产物(compiled.scrapeRegions), 播放器只按 id 透传, 不理解其几何。
    for (const [id, phases] of Object.entries(state.scrapes || {})) {
      this.rig.setScrape?.(id, phases, this.clip.scrapeRegions?.[id] || null)
    }
    // 点样色带与溶剂润湿是另两种板面痕迹, 同一条透传纪律(几何在 regions, 通道只带进度)
    for (const [id, fills] of Object.entries(state.spots || {})) {
      this.rig.setSpot?.(id, fills, this.clip.spotRegions?.[id] || null)
    }
    for (const [id, front] of Object.entries(state.wets || {})) {
      this.rig.setWet?.(id, front, this.clip.wetRegions?.[id] || null)
    }
    // 主轴通道只带**开关**(0/1), 相位在 tick 里按 rpm 累加 —— 通道值仍是 t 的纯函数
    for (const [id, on] of Object.entries(state.spindles || {})) {
      this.rig.setSpindle?.(id, on > 0.5)
    }
    // 取放吸附补间与连续通道一样是 t 的纯函数; 回家重放路径里逐事件推进,
    // 保证释放事件看到的是"吸附已完成"的位姿(与自然播放一致)。
    this.rig.updateToolTween?.(t)
    // 粉柱写在最后: 它只写粉柱节点自己的局部 position/scale/材质色, 没有任何下游读它,
    // 也不再依赖当帧世界姿态 —— 2026-08-13 粉的落点改成恒锚在腔的 c1 端(粉被滤纸内衬
    // 拦住, 翻料倒粉时跟着桶转、相对桶不动)之后, 原先"必须排在 updateToolTween 之后"
    // 的次序约束就没有了。值成对交付({fill: mm³, tint: 0..1}), 换算在 updatePowders 里做。
    this.rig.updatePowders?.(state.powders || {})
  }

  /**
   * 功能: 触发一个离散事件.
   * @param {object} event 事件
   * @param {boolean} fireCamera 是否执行镜头类事件
   * @returns {void}
   */
  _fire(event, fireCamera) {
    const payload = event.payload || {}
    if (event.kind === 'tool') {
      // 传入事件时刻启用吸附补间: 锁紧滑入 mount_transform, 释放滑回停靠位。
      // snap=true 是"本段起手时刀已在腕上"的声明(转移片段的第一步), 不是取刀动作:
      // 直接就位, 不走吸附补间, 也不该报超限。
      if (payload.action === 'lock') this.rig.lockTool(payload.id, event.t, { snap: payload.snap === true })
      else if (payload.action === 'release') this.rig.releaseTool(payload.id, event.t)
    } else if (event.kind === 'attach') {
      // 传事件时刻: kind=item 且带 mountLocal 的载荷在换父后向"四销笼中心"做位置磁吸
      // (姿态保留), 修掉 CAD 座位与取料示教点的平移失配 —— 见 MachineStateDriver.attach。
      this.rig.attach(payload.id, payload.parent, event.t)
    } else if (event.kind === 'detach') {
      // 带 dock 的 detach = 载荷落位(换父 + 吸附到编译期算好的座位位姿); 不带则是
      // 老语义的纯换父。dockPayload 内部仍走 detach, 所以两条路的父级处理完全一致。
      // snap=true 是"本段起手时件已在爪中"的声明(放件半程片段的第一步, 编译器
      // preload_payload 发出), 与 tool.snap 同义: 直接就位, 不走吸附补间也不报超限。
      const parent = payload.parent || payload.to
      if (payload.dock) this.rig.dockPayload?.(payload.id, parent, payload.dock, event.t, { snap: payload.snap === true })
      else this.rig.detach(payload.id, parent)
    } else if (event.kind === 'plate') {
      // 板舞台是可选装置(动作页与演示页都经 useMotionStack 挂; 没挂就静默跳过,
      // 片段照常演机器动作)。
      this.rig.setPlate?.(payload)
    } else if (event.kind === 'state') {
      this.rig.setState(payload.id, payload.value)
    } else if (event.kind === 'highlight') {
      this.rig.setHighlight(payload.on === false ? [] : [payload.node].flat().filter(Boolean))
    } else if (event.kind === 'camera' && fireCamera && this.cameraRig) {
      this._flyCamera(payload)
    }
  }

  /**
   * 功能: 执行镜头事件(station 机位 / 显式 pos+target / 预设机位).
   * @param {object} payload 镜头参数
   * @returns {void}
   */
  _flyCamera(payload) {
    if (payload.station && this.manifest) {
      const station = (this.manifest.stations || []).find((item) => item.id === payload.station)
      if (station?.camera?.pos) {
        this.cameraRig.flyTo({ pos: station.camera.pos, target: station.camera.target }, true)
        return
      }
    }
    if (payload.pos && payload.target) {
      this.cameraRig.flyTo({ pos: payload.pos, target: payload.target }, true)
    } else if (payload.preset) {
      this.cameraRig.applyPreset(payload.preset, true)
    }
  }

  /**
   * 功能: 通知 UI 当前状态.
   * @returns {void}
   */
  _notify() {
    if (!this.onChange || !this.clip) return
    this.onChange({
      time: this.time,
      duration: this.clip.duration,
      playing: this.playing,
      speed: this.speed,
      stepIndex: stepIndexAt(this.clip, this.time),
    })
  }

  /**
   * 功能: 停止并清场.
   * @returns {void}
   */
  dispose() {
    this.playing = false
    this.rig?.home()
    this.clip = null
  }
}
