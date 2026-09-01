// 脚本节点树前端工具
// ===================
// AID 推导 / 控制流子块 / 节点定位与变更 / 节点与表达式文本化.
// block 名与后端 schema.child_blocks 完全一致 (then/elif{n}/else/body/catch{n}/finally/br{n}),
// 以保证前端高亮的 AID 与 VM 运行期 current_aid 对齐.

export function isControl(node) {
  return ['if', 'for', 'while', 'repeat', 'try', 'parallel', 'with_resources'].includes(node.op)
}

export function childAid(parentAid, block, idx) {
  return `${parentAid}/${block}/${idx}`
}

// 控制流节点的子块 [{ block, label, nodes }] (供递归渲染)
export function controlBlocks(node) {
  const blocks = []
  if (node.op === 'if') {
    blocks.push({ block: 'then', label: '#true', nodes: node.then || [] })
    ;(node.elifs || []).forEach((br, i) =>
      blocks.push({ block: `elif${i}`, label: `elif ${exprText(br.cond)}`, nodes: br.body || [] }))
    blocks.push({ block: 'else', label: '#false', nodes: node.else || [] })
  } else if (node.op === 'for' || node.op === 'while' || node.op === 'repeat') {
    blocks.push({ block: 'body', label: '循环体', nodes: node.body || [] })
  } else if (node.op === 'try') {
    blocks.push({ block: 'body', label: 'try', nodes: node.body || [] })
    ;(node.catch || []).forEach((h, i) =>
      blocks.push({ block: `catch${i}`, label: `catch ${h.error}`, nodes: h.body || [] }))
    if (node.finally) blocks.push({ block: 'finally', label: 'finally', nodes: node.finally || [] })
  } else if (node.op === 'parallel') {
    ;(node.branches || []).forEach((br, i) => blocks.push({ block: `br${i}`, label: `分支 ${i}`, nodes: br || [] }))
  } else if (node.op === 'with_resources') {
    blocks.push({ block: 'body', label: '持有资源期间', nodes: node.body || [] })
  }
  return blocks
}

// 取某 block 的真实数组引用 (用于变更; 不存在则创建)
function blockArray(node, block) {
  if (block === 'then') return (node.then || (node.then = []))
  if (block === 'else') return (node.else || (node.else = []))
  if (block === 'body') return (node.body || (node.body = []))
  if (block === 'finally') return (node.finally || (node.finally = []))
  if (block.startsWith('elif')) return (node.elifs[+block.slice(4)].body || (node.elifs[+block.slice(4)].body = []))
  if (block.startsWith('catch')) return (node.catch[+block.slice(5)].body || (node.catch[+block.slice(5)].body = []))
  if (block.startsWith('br')) return (node.branches[+block.slice(2)] || (node.branches[+block.slice(2)] = []))
  return null
}

// 按 AID 定位 { list, index, node }; list 为承载该节点的真实数组引用 (供变更)
export function locate(doc, aid) {
  const segs = aid.split('/')
  let list = doc.body
  let node = null
  let index = -1
  for (let i = 0; i < segs.length; i += 2) {
    const block = segs[i]
    const idx = Number(segs[i + 1])
    if (i > 0) list = blockArray(node, block)
    index = idx
    node = list[idx]
  }
  return { list, index, node }
}

// 新建节点 (各 op 的默认骨架)
export function newNode(op) {
  switch (op) {
    case 'call': return { op: 'call', action: '', args: {}, mode: null }
    case 'run_script': return { op: 'run_script', script: '', inputs: {}, outputs: {} }
    case 'assign': return { op: 'assign', target: { var: '' }, value: { lit: 0 } }
    case 'if': return { op: 'if', cond: { lit: true }, then: [], elifs: [], else: [] }
    case 'for': return { op: 'for', var: '', start: { lit: 0 }, stop: { lit: 0 }, step: { lit: 1 }, body: [] }
    case 'while': return { op: 'while', cond: { lit: true }, body: [], max_iter: 100000 }
    case 'repeat': return { op: 'repeat', body: [], until: { lit: true }, max_iter: 100000 }
    case 'raise': return { op: 'raise', error: 'ERROR', message: { lit: '' } }
    case 'try': return { op: 'try', body: [], catch: [{ error: '*', body: [] }], finally: [] }
    case 'parallel': return { op: 'parallel', branches: [[], []], join: 'all' }
    case 'with_resources': return { op: 'with_resources', resources: [], body: [] }
    case 'human': return { op: 'human', kind: 'confirm', prompt: { lit: '请确认' }, fields: [], assign_choice: null }
    case 'comment': return { op: 'comment', text: '' }
    default: return { op }
  }
}

// ---- 文本化 (表格列展示) ----

export function exprText(e) {
  if (e === null || e === undefined) return ''
  if (typeof e !== 'object') return String(e)
  if ('lit' in e) return typeof e.lit === 'string' ? `"${e.lit}"` : JSON.stringify(e.lit)
  if ('var' in e) return '$' + e.var
  if ('binop' in e) return `${exprText(e.left)} ${e.binop} ${exprText(e.right)}`
  if ('unop' in e) return `${e.unop} ${exprText(e.operand)}`
  if ('call' in e) return `${e.call}(${(e.args || []).map(exprText).join(', ')})`
  if ('index' in e) return `${exprText(e.index)}[${exprText(e.key)}]`
  if ('field' in e) return `${exprText(e.field)}.${e.name}`
  return JSON.stringify(e)
}

export function nodeAction(node, actions = null, scripts = null) {
  switch (node.op) {
    case 'call': {
      // 动作行: 优先「动作 中文名 · id」, 无 label 时回退「动作 id」, 未选动作为「动作 ?」
      if (!node.action) return '动作 ?'
      const def = actions && actions.find((a) => a.name === node.action)
      return def && def.label ? `动作 ${def.label} · ${node.action}` : `动作 ${node.action}`
    }
    case 'run_script': {
      // 子流程行: 优先「运行脚本 中文名 · id」, 无 label 时回退「运行脚本 id」, 未选为「运行脚本 ?」
      if (!node.script) return '运行脚本 ?'
      const sdef = scripts && scripts.find((s) => s.name === node.script)
      return sdef && sdef.label ? `运行脚本 ${sdef.label} · ${node.script}` : `运行脚本 ${node.script}`
    }
    case 'assign': return '赋值'
    case 'if': return `若 ${exprText(node.cond)}`
    case 'for': return node.in ? `循环 ${node.var} ∈ ${exprText(node.in)}`
      : `循环 ${node.var} = ${exprText(node.start)}..${exprText(node.stop)}`
    case 'while': return `当 ${exprText(node.cond)}`
    case 'repeat': return `重复 直到 ${exprText(node.until)}`
    case 'raise': return `抛出 ${node.error || ''}`
    case 'try': return 'try'
    case 'parallel': return `并行 (${(node.branches || []).length} 分支)`
    case 'with_resources': return `持有资源 ${(node.resources || []).join(', ') || '?'}`
    case 'human': return `人工 ${node.kind || ''}`
    case 'comment': return `# ${node.text || ''}`
    default: return node.op
  }
}

export function nodeInput(node) {
  if (node.op === 'call') return Object.entries(node.args || {}).map(([k, v]) => `${k}=${exprText(v)}`).join(', ')
  if (node.op === 'run_script') return Object.entries(node.inputs || {}).map(([k, v]) => `${k}=${exprText(v)}`).join(', ')
  if (node.op === 'assign') return `${node.target ? '$' + node.target.var : ''} = ${exprText(node.value)}`
  if (node.op === 'raise') return exprText(node.message)
  if (node.op === 'human') return exprText(node.prompt)
  return ''
}

export function nodeOutput(node) {
  if (node.op === 'call' && node.assign) return '$' + node.assign.var
  if (node.op === 'run_script') return Object.entries(node.outputs || {}).map(([k, v]) => `${k}→$${v.var}`).join(', ')
  if (node.op === 'human' && node.assign_choice) return '$' + node.assign_choice.var
  return ''
}
