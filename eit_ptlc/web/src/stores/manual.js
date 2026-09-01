// 单点控制 (PC Manual Mode) 会话状态
// ------------------------------------------------------------------
// 一个会话跨工位共享: 用户在设备页切工位时不该被踢出单点模式, 故会话与心跳放在
// store 里, 面板只负责订阅某个工位的实时值。
//
// 三层防卡死里的第一层在面板 (pointerup/blur 立刻发 jog_stop), 第二层第三层分别在
// 后端 ManualService 与 PLC 的 PLC_PCManual —— store 只保证心跳按时发出。
import { defineStore } from 'pinia'
import { api, errText } from '../api'

const KEEPALIVE_MS = 1000   // 后端会话 TTL 3.5s
// 会话中要看到点动位移与到位反馈的即时变化, 故 500ms; 只是开着面板看状态时降到 2s ——
// 每次 state 都是一整批 OPC UA 读 (该工位全部执行器×4 + 轴×9), 空转没必要压 PLC。
const POLL_ACTIVE_MS = 500
const POLL_IDLE_MS = 2000

export const useManualStore = defineStore('manual', {
  state: () => ({
    enabled: false,        // 后端已建立会话
    active: false,         // PLC 侧 PC_Manual_Active (唯一权威: 为 false 时下发无效)
    rejectText: '',        // PLC 给出的未生效原因
    busy: false,           // 进入/退出进行中
    error: '',
    points: {},            // station -> {cylinders, axes}
    allStations: [],
    state: {},             // 当前订阅工位的实时值 {globals, cylinders, axes, jogging}
    station: '',           // 当前订阅工位
    _beat: null,
    _poll: null,
    _pollPeriod: 0,
  }),

  getters: {
    // 档位/设备状态回显: PLC 侧 ManualAuto TRUE=自动档
    manualAuto: (s) => s.state?.globals?.manual_auto === true,
    modeState: (s) => s.state?.globals?.mode_state,
    alarmWord: (s) => s.state?.globals?.cylinder_alarm ?? 0,
    stationPoints: (s) => (s.points?.[s.station] ?? { cylinders: [], axes: [] }),
  },

  actions: {
    async loadPoints() {
      if (this.allStations.length) {
        return
      }
      try {
        const data = await api.pcManualPoints()
        this.points = data.stations || {}
        this.allStations = data.all_stations || []
      } catch (e) {
        this.error = errText(e)
      }
    },

    async enter() {
      this.busy = true
      this.error = ''
      try {
        this.applyState(await api.pcManualEnter())
        this.enabled = true
        this.startBeat()
        this.restartPoll()   // 切到会话中的高频轮询, 不等下一拍
      } catch (e) {
        this.error = errText(e)
        this.enabled = false
      } finally {
        this.busy = false
      }
    },

    async exit() {
      this.busy = true
      this.stopBeat()
      try {
        await api.pcManualExit()
      } catch (e) {
        this.error = errText(e)
      } finally {
        this.enabled = false
        this.active = false
        this.busy = false
        this.restartPoll()   // 回落到空闲低频轮询
        await this.refresh()
      }
    },

    startBeat() {
      this.stopBeat()
      this._beat = setInterval(() => {
        api.pcManualKeepalive().catch(() => {
          // 心跳失败多半是会话已被后端收走; 下一轮 refresh 会把状态纠正过来
        })
      }, KEEPALIVE_MS)
    },

    stopBeat() {
      if (this._beat !== null) {
        clearInterval(this._beat)
        this._beat = null
      }
    },

    applyState(data) {
      if (!data) {
        return
      }
      this.enabled = data.enabled === true
      this.active = data.active === true
      this.rejectText = data.reject_text || ''
      if (data.cylinders || data.axes || data.globals) {
        this.state = data
      }
      if (!this.enabled) {
        this.stopBeat()
      }
    },

    async refresh() {
      try {
        this.applyState(await api.pcManualState(this.station || undefined))
      } catch (e) {
        this.error = errText(e)
      }
    },

    // 面板挂载/切工位时调用: 订阅某工位并开轮询 (轮询本身也充当会话存活证据)
    watchStation(station) {
      this.station = station
      this.stopPoll()
      this.refresh()
      this.restartPoll()
    },

    restartPoll() {
      this.stopPoll()
      const period = this.enabled ? POLL_ACTIVE_MS : POLL_IDLE_MS
      this._pollPeriod = period
      this._poll = setInterval(() => {
        // 后台标签页跳过纯读取拍 (每拍是该工位全部执行器+轴的一整批 OPC UA 读, 单位代价全库最高)。
        // keepalive 心跳独立于此不受影响; 点动必然在前台。换档检查保留 (廉价, 保证回见后档位正确)。
        if (!document.hidden) this.refresh()
        // 会话开/关后切换轮询频率 (下一拍生效即可)
        if (this.station && this._pollPeriod !== (this.enabled ? POLL_ACTIVE_MS : POLL_IDLE_MS)) {
          this.restartPoll()
        }
      }, period)
    },

    stopPoll() {
      if (this._poll !== null) {
        clearInterval(this._poll)
        this._poll = null
      }
    },
  },
})
