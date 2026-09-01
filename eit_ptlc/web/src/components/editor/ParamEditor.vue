<script setup>
// 参数编辑: 按所选节点 op 渲染其字段 (call 的动作+入参+输出绑定; 控制流条件; human; 等)
import { computed, onMounted, ref, useId } from 'vue'
import ValueInput from './ValueInput.vue'
import { useEditorStore } from '../../stores/editor'
import { api } from '../../api'

const editor = useEditorStore()
const uid = useId()   // label for/id 前缀 (各 op 模板互斥渲染, 字段名不撞)
const node = computed(() => editor.selectedNode)
const vars = computed(() => editor.variables)
const scripts = computed(() => editor.operations)
const actionDef = computed(() => editor.actionsCache.find((a) => a.name === node.value?.action) || null)

// 设备资源表: with_resources 区间只能声明共享资源 (独占资源只能写在脚本根 resources)
const sharedResources = ref([])
onMounted(async () => {
  editor.ensureActions()
  try {
    const data = await api.listResources()
    sharedResources.value = (data.resources || []).filter((r) => r.mode === 'shared')
  } catch (e) {
    sharedResources.value = []   // 后端未起/资源门未就绪: 面板显示提示, 不阻断其它节点编辑
  }
})

function hasResource(id) { return (node.value.resources || []).includes(id) }
function toggleResource(id, on) {
  if (!node.value.resources) node.value.resources = []
  const idx = node.value.resources.indexOf(id)
  if (on && idx < 0) node.value.resources.push(id)
  if (!on && idx >= 0) node.value.resources.splice(idx, 1)
  touch()
}

function touch() { editor.markDirty() }
function defExpr(p) {
  const d = p.default
  if (d !== null && d !== undefined) return { lit: d }
  if (p.type === 'bool') return { lit: false }
  // 可选无默认的数值参数 (泵速度/延时): 空值 -> 显示占位符 (真实泵档数字), 不兜底误导的 0
  if ((p.type === 'int' || p.type === 'float') && !p.required) return { lit: '' }
  if (p.type === 'int' || p.type === 'float') return { lit: 0 }   // 必填无默认: 维持原行为
  return { lit: '' }
}
function overridden(p) {
  return !!(node.value.args && Object.prototype.hasOwnProperty.call(node.value.args, p.name))
}
function argVal(p) { return overridden(p) ? node.value.args[p.name] : defExpr(p) }
function unsettable(p) { return !p.required && (p.default === null || p.default === undefined) }
function placeholderFor(p) {
  // 仅"未覆写且有泵档提示"的参数显示占位 (真实执行值), 让用户知道留空即按此值执行
  if (overridden(p)) return ''
  if (p.default_hint !== null && p.default_hint !== undefined) return `${p.default_hint} · 泵档默认`
  return ''
}
function setArg(name, expr) {
  if (!node.value.args) node.value.args = {}
  node.value.args[name] = expr
  touch()
}
function onArg(p, expr) {
  // 清空 (空字面量) = 取消覆写, 回退默认 (泵档); 否则写入覆写
  if (expr && typeof expr === 'object' && 'lit' in expr && expr.lit === '') {
    if (node.value.args && p.name in node.value.args) { delete node.value.args[p.name]; touch() }
    return
  }
  setArg(p.name, expr)
}
function onActionChange(name) {
  node.value.action = name
  node.value.args = {}
  touch()
}
function toggleAssign(on) {
  node.value.assign = on ? { var: vars.value[0]?.name || '' } : undefined
  touch()
}
</script>

<template>
  <div v-if="!node" class="empty">从中间表格选择一个节点以编辑</div>
  <div v-else class="param-editor">
    <div class="pe-op">{{ node.op }}</div>

    <!-- call -->
    <template v-if="node.op === 'call'">
      <div class="field">
        <label :for="`${uid}-action`">动作 (原子指令)</label>
        <select :id="`${uid}-action`" :value="node.action" @change="onActionChange($event.target.value)">
          <option value="">— 选择动作 —</option>
          <option v-for="a in editor.actionsCache" :key="a.name" :value="a.name">{{ a.label }} ({{ a.name }})</option>
        </select>
      </div>
      <div v-for="p in (actionDef?.params || [])" :key="p.name" class="field">
        <label>{{ p.label }} <span v-if="p.required" class="req">*</span>
          <router-link v-if="p.is_point && typeof argVal(p).lit === 'string' && argVal(p).lit" class="pt-jump"
                       :to="`/points/robot/${encodeURIComponent(argVal(p).lit)}`" title="跳转到点位管理页查看/修改">→ 点位</router-link>
        </label>
        <ValueInput :model-value="argVal(p)" :type="p.type" :options="p.options" :minimum="p.minimum" :maximum="p.maximum" :vars="vars"
                    :placeholder="placeholderFor(p)" :unsettable="unsettable(p)" :label="p.label"
                    @update:model-value="onArg(p, $event)" />
      </div>
      <div class="field">
        <label><input type="checkbox" :checked="!!node.assign" @change="toggleAssign($event.target.checked)" /> 结果赋值到变量</label>
        <select v-if="node.assign" v-model="node.assign.var" aria-label="结果赋值目标变量" @change="touch">
          <option v-for="v in vars" :key="v.name" :value="v.name">${{ v.name }}</option>
        </select>
      </div>
    </template>

    <!-- run_script -->
    <template v-else-if="node.op === 'run_script'">
      <div class="field">
        <label :for="`${uid}-script`">子脚本</label>
        <select :id="`${uid}-script`" v-model="node.script" @change="touch">
          <option value="">— 选择脚本 —</option>
          <option v-for="s in scripts" :key="s.name" :value="s.name">{{ s.label }} ({{ s.kind }})</option>
        </select>
      </div>
      <div class="field"><label>输入 (子脚本入参 = 表达式)</label></div>
      <div v-for="(v, k) in node.inputs" :key="'i' + k" class="kvrow">
        <span class="kvkey">{{ k }}</span>
        <ValueInput :model-value="v" :vars="vars" :label="String(k)" @update:model-value="node.inputs[k] = $event; touch()" />
        <button class="mini" :title="'移除参数 ' + k" :aria-label="'移除参数 ' + k" @click="delete node.inputs[k]; touch()">×</button>
      </div>
      <div class="field"><label>输出 (子脚本出参 → 本脚本变量)</label></div>
      <div v-for="(v, k) in node.outputs" :key="'o' + k" class="kvrow">
        <span class="kvkey" :id="`${uid}-o-${k}`">{{ k }}</span>
        <select v-model="node.outputs[k].var" :aria-labelledby="`${uid}-o-${k}`" @change="touch">
          <option v-for="vv in vars" :key="vv.name" :value="vv.name">${{ vv.name }}</option>
        </select>
        <button class="mini" :title="'移除参数 ' + k" :aria-label="'移除参数 ' + k" @click="delete node.outputs[k]; touch()">×</button>
      </div>
    </template>

    <!-- assign -->
    <template v-else-if="node.op === 'assign'">
      <div class="field">
        <label :for="`${uid}-target`">目标变量</label>
        <select :id="`${uid}-target`" v-model="node.target.var" @change="touch">
          <option v-for="v in vars" :key="v.name" :value="v.name">${{ v.name }}</option>
        </select>
      </div>
      <div class="field"><label>值</label>
        <ValueInput :model-value="node.value" :vars="vars" label="值" @update:model-value="node.value = $event; touch()" />
      </div>
    </template>

    <!-- if -->
    <template v-else-if="node.op === 'if'">
      <div class="field"><label>条件</label>
        <ValueInput :model-value="node.cond" type="bool" :vars="vars" label="条件" @update:model-value="node.cond = $event; touch()" />
      </div>
      <button class="mini" @click="editor.addElif(node)">+ elif 分支</button>
    </template>

    <!-- for -->
    <template v-else-if="node.op === 'for'">
      <div class="field"><label :for="`${uid}-loopvar`">循环变量</label>
        <select :id="`${uid}-loopvar`" v-model="node.var" @change="touch"><option v-for="v in vars" :key="v.name" :value="v.name">${{ v.name }}</option></select>
      </div>
      <div class="field"><label>起始</label><ValueInput :model-value="node.start" type="int" :vars="vars" label="起始" @update:model-value="node.start = $event; touch()" /></div>
      <div class="field"><label>终止</label><ValueInput :model-value="node.stop" type="int" :vars="vars" label="终止" @update:model-value="node.stop = $event; touch()" /></div>
      <div class="field"><label>步长</label><ValueInput :model-value="node.step || { lit: 1 }" type="int" :vars="vars" label="步长" @update:model-value="node.step = $event; touch()" /></div>
    </template>

    <!-- while / repeat -->
    <template v-else-if="node.op === 'while'">
      <div class="field"><label>条件 (为真则继续)</label><ValueInput :model-value="node.cond" type="bool" :vars="vars" label="条件 (为真则继续)" @update:model-value="node.cond = $event; touch()" /></div>
    </template>
    <template v-else-if="node.op === 'repeat'">
      <div class="field"><label>直到 (为真则结束)</label><ValueInput :model-value="node.until" type="bool" :vars="vars" label="直到 (为真则结束)" @update:model-value="node.until = $event; touch()" /></div>
    </template>

    <!-- raise -->
    <template v-else-if="node.op === 'raise'">
      <div class="field"><label :for="`${uid}-error`">错误名</label><input :id="`${uid}-error`" type="text" v-model="node.error" @input="touch" /></div>
      <div class="field"><label>消息</label><ValueInput :model-value="node.message || { lit: '' }" type="string" :vars="vars" label="消息" @update:model-value="node.message = $event; touch()" /></div>
    </template>

    <!-- try -->
    <template v-else-if="node.op === 'try'">
      <div class="field" v-for="(h, i) in node.catch" :key="i">
        <label :for="`${uid}-catch-${i}`">catch 错误名 (* 通配)</label><input :id="`${uid}-catch-${i}`" type="text" v-model="h.error" @input="touch" />
      </div>
      <button class="mini" @click="editor.addCatch(node)">+ catch</button>
    </template>

    <!-- parallel -->
    <template v-else-if="node.op === 'parallel'">
      <div class="field"><label :for="`${uid}-join`">汇合</label>
        <select :id="`${uid}-join`" v-model="node.join" @change="touch"><option value="all">all (全部完成)</option><option value="any">any (任一完成)</option></select>
      </div>
      <button class="mini" @click="editor.addBranch(node)">+ 分支</button>
    </template>

    <!-- with_resources: 区间持有共享设备资源, 进入取得/退出释放, 由资源门按引用计数开关设备 -->
    <template v-else-if="node.op === 'with_resources'">
      <div class="field" v-for="r in sharedResources" :key="r.id">
        <label>
          <input type="checkbox" :checked="hasResource(r.id)" @change="toggleResource(r.id, $event.target.checked)" />
          {{ r.label }} · {{ r.id }}
          <span class="hint">当前 {{ r.holders }} 个持有者</span>
        </label>
      </div>
      <div class="field" v-if="!sharedResources.length">
        <label>无可选共享资源 (资源表未就绪或未声明 shared 资源)</label>
      </div>
    </template>

    <!-- human -->
    <template v-else-if="node.op === 'human'">
      <div class="field"><label :for="`${uid}-kind`">类型</label>
        <select :id="`${uid}-kind`" v-model="node.kind" @change="touch"><option value="confirm">确认</option><option value="input">输入</option><option value="show_pic">看图</option></select>
      </div>
      <div class="field"><label>提示</label><ValueInput :model-value="node.prompt || { lit: '' }" type="string" :vars="vars" label="提示" @update:model-value="node.prompt = $event; touch()" /></div>
      <div class="field"><label><input type="checkbox" :checked="!!node.assign_choice" @change="node.assign_choice = $event.target.checked ? { var: vars[0]?.name || '' } : null; touch()" /> 选择结果赋值</label>
        <select v-if="node.assign_choice" v-model="node.assign_choice.var" aria-label="选择结果赋值到变量" @change="touch"><option v-for="v in vars" :key="v.name" :value="v.name">${{ v.name }}</option></select>
      </div>
    </template>

    <!-- comment -->
    <template v-else-if="node.op === 'comment'">
      <div class="field"><label :for="`${uid}-text`">注释</label><input :id="`${uid}-text`" type="text" v-model="node.text" @input="touch" /></div>
    </template>
  </div>
</template>

<style scoped>
.pt-jump { margin-left: 8px; color: var(--accent); cursor: pointer; font-size: var(--fs-12); text-decoration: none; }
.hint { margin-left: 8px; opacity: 0.6; font-size: var(--fs-12); }
</style>
