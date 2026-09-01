// 统一点位目录 store: 点位树 (机器人 / PLC伺服) + 当前选中详情
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, errText } from '../api'

export const usePointsStore = defineStore('points', () => {
  const tree = ref(null) // { robot:{label,groups:[{key,label,points:[]}]}, plc_servo:{...} }
  const detail = ref(null) // 当前选中点位详情
  const loading = ref(false)
  const error = ref(null)

  async function loadTree(force = false) {
    if (tree.value && !force) return
    loading.value = true
    error.value = null
    try {
      tree.value = await api.listPoints()
    } catch (e) {
      error.value = errText(e)
    } finally {
      loading.value = false
    }
  }

  async function loadDetail(category, id) {
    if (!category || !id) {
      detail.value = null
      return
    }
    try {
      detail.value = await api.getPoint(category, id)
    } catch (e) {
      detail.value = null
      error.value = errText(e)
    }
  }

  return { tree, detail, loading, error, loadTree, loadDetail }
})
