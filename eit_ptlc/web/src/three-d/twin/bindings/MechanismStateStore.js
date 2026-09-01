export const MECHANISM_STALE_MS = 500

function stampMs(value, fallback) {
  if (!Number.isFinite(value)) return fallback
  return value < 1e12 ? value * 1000 : value
}

function hasBoolean(record, key) {
  return Object.prototype.hasOwnProperty.call(record, key) && typeof record[key] === 'boolean'
}

function hasOwn(record, key) {
  return Object.prototype.hasOwnProperty.call(record, key)
}

/**
 * 气缸、阀和泵的只读状态账本。commanded 与 confirmed 分开保存；有传感器反馈时
 * effective 永远取 confirmed，后到的命令态只更新 commanded，不会覆盖真实反馈。
 *
 * 另有一个可选的 `moving` 位，表示"命令已下发但行程未结束"（见 push 里的注释）。
 * 它与 commanded/confirmed 正交：只说阶段，不说位置，也永远不能拿来冒充到位。
 */
export class MechanismStateStore {
  constructor({ staleMs = MECHANISM_STALE_MS, knownIds = [] } = {}) {
    this.staleMs = staleMs
    this.knownIds = new Set(knownIds)
    this.states = new Map()
    this.sequences = new Set()
    this.forceResync = false
  }

  push(event, arrivalMs = Date.now()) {
    if (!event?.states || typeof event.states !== 'object' || Array.isArray(event.states)) return false
    const ts = stampMs(event.ts, arrivalMs)
    const seq = Number.isFinite(event.seq) ? Number(event.seq) : null
    const explicitResync = this.forceResync
    const reconnect = explicitResync || Object.keys(event.states).some((id) => {
      const current = this.states.get(id)
      return current?.arrivalMs && arrivalMs - current.arrivalMs > this.staleMs
    })
    if (reconnect) this.sequences.clear()
    this.forceResync = false
    if (seq !== null && this.sequences.has(seq)) return false
    if (seq !== null) {
      this.sequences.add(seq)
      if (this.sequences.size > 256) this.sequences.delete(this.sequences.values().next().value)
    }

    let changed = false
    for (const [id, raw] of Object.entries(event.states)) {
      if (!id || (this.knownIds.size && !this.knownIds.has(id))) continue
      const record = raw && typeof raw === 'object' ? raw : { commanded: Boolean(raw) }
      const current = this.states.get(id) || {}
      if (Number.isFinite(current.ts) && ts < current.ts) continue
      const wasStale = explicitResync
        || (current.arrivalMs && arrivalMs - current.arrivalMs > this.staleMs)
      const next = {
        ...current,
        id,
        ts,
        seq,
        arrivalMs,
        source: record.source || event.source || current.source || 'estimated',
        resyncedAt: wasStale ? arrivalMs : current.resyncedAt,
      }
      if (hasBoolean(record, 'commanded')) next.commanded = record.commanded
      if (hasBoolean(record, 'confirmed')) {
        next.confirmed = record.confirmed
      } else if (hasOwn(record, 'confirmed') && record.confirmed === null) {
        delete next.confirmed
      }
      // moving = "命令已下发但行程未结束"。发布方只有走 di_or_dwell 的吸盘翻转
      // (robot_controller._TWIN_INFLIGHT_ACTIONS), 别的机构条目里根本没有这个键 ——
      // 缺省视同 false(已就位), 老后端与本 store 因此完全兼容。
      // 它不参与 effective 的推导: commanded/confirmed 的语义一个字不动, 这里只是把
      // "还在路上"如实带给绑定层, 由那边决定动画保持在终点前。
      //
      // **不粘**, 与 commanded/confirmed 的粘性刻意相反: 那两个说的是**位置**(没给新值
      // 就该保留旧值), 这个说的是**阶段**。"缺了就当还在走"会在发布方停发时把动画永久
      // 钉在终点前 —— 行程中卸刀, mechanism_snapshot 就不再发布这个机构了。
      // 阶段位的安全缺省只能是"已就位"。
      next.moving = hasBoolean(record, 'moving') ? record.moving : false
      // expectedS = 本方向**上一程的实测行程耗时**(秒), 由上位机量 DO→DI 得出, 供绑定层
      // 按真速配速。与 moving 相反, 它是**粘的**: 这是速度标定值不是阶段位, 中途某帧漏发
      // 不该让动画忽然变速; 没有样本时后端整个省略该键, 前端回退 spec.transitionS 标称值。
      if (Number.isFinite(record.expectedS) && record.expectedS > 0) next.expectedS = record.expectedS
      if (record.available === false) next.available = false
      else if (record.available === true || hasBoolean(record, 'commanded') || hasBoolean(record, 'confirmed')) {
        next.available = true
      }
      this.states.set(id, next)
      changed = true
    }
    return changed
  }

  /** 保留末态；重连后的第一批状态允许 seq 重置并标记重新同步。 */
  markDisconnected() {
    if (this.states.size) this.forceResync = true
  }

  /**
   * 彻底复位: 丢弃全部机构末态。向后 seek 必须先调它, 否则关键帧会被**静默丢弃**。
   *
   * push() 里有一道逐机构的单调时间戳闸门:
   *     if (Number.isFinite(current.ts) && ts < current.ts) continue
   * markDisconnected() 只置 forceResync, 重连分支也只清 sequences —— states[].ts
   * 一直留着。于是回放向后跳之后, 每一条比"上次见过的"更早的 mechanism_state 都会
   * 被逐 id 悄悄跳过, 气缸与阀停在未来的状态上, 而且没有任何报错。
   *
   * 不要用"把关键帧时间戳改成 max(ts)"绕开这道闸门 —— 那会连带破坏 stale 与
   * estimated 的判定, 把推算值伪装成实测值, 对事故追溯是更坏的结果。
   *
   * 清空是安全的: seek 紧接着就会用块关键帧里合并后的完整逐机构记录重新播种。
   */
  reset() {
    this.states.clear()
    this.sequences.clear()
    this.forceResync = false
  }

  pushCommand(id, commanded, arrivalMs = Date.now()) {
    if (!id || typeof commanded !== 'boolean') return false
    return this.push({
      type: 'mechanism_state',
      states: { [id]: { commanded, source: 'commanded' } },
      ts: arrivalMs,
      source: 'commanded',
    }, arrivalMs)
  }

  sample(nowMs = Date.now()) {
    const result = {}
    for (const [id, state] of this.states) {
      const stale = nowMs - (state.arrivalMs || 0) > this.staleMs
      // 姿态取"最后一次实测值", **不看墙钟新鲜度**: confirmed 与 commanded 同在一条消息里
      // 到达, 判过期时两者一样旧 —— 一个是实测一个是假设, 因时钟走过 staleMs 就从实测退到
      // 假设, 等于把渲染循环的卡顿当成机器动了。sample() 每渲染帧调一次, 主线程一次 GC/
      // 重帧/后台标签页节流就够翻一次; 命令态与反馈态不一致的机构(现场 col_lift: 线圈断电
      // 却停在动点)于是整程往返, 再被 resynced 硬吸附成闪烁。
      // 后端真不知道位置时会显式发 confirmed:null, push() 据此删掉 confirmed —— 那才是
      // 回落到 commanded 的唯一依据, 由数据说了算, 不由时钟说了算。
      const measured = typeof state.confirmed === 'boolean'
      result[id] = {
        ...state,
        effective: measured ? state.confirmed : state.commanded,
        stale,
        // 跟随 effective 的**来源**而非数据年龄: 否则会出现"取自实测却标推定"的自相矛盾。
        // 数据有多旧由 stale 如实告知, 新鲜度信号一点没丢。
        estimated: !measured,
        resynced: Boolean(state.resyncedAt && nowMs - state.resyncedAt <= this.staleMs),
      }
    }
    return result
  }
}
