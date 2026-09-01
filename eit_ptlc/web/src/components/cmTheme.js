// CodeMirror 6 主题: 还原 VS Code Dark+ / Light+ 配色 + YAML 标量识别 (数字/布尔/null 单独上色)。
// 同一套 HighlightStyle 同时服务 YAML 与 ST (结构化文本) tag, ST 分词器见 stLang.js。
//
// 文法事实 (@lezer/yaml styleTags): 键=definition(propertyName), 引号串=string, 注释=lineComment,
// 分隔符 : , -=separator, 括号=squareBracket/brace; 但**未引号标量 (含数字/布尔)统一为 Literal→content,
// 文法不分数字与字符串**。故除按 tag 调色 (HighlightStyle) 外, 用 scalarHighlighter 装饰插件按文本正则
// 给"值"Literal 额外标 number/bool/null 类, 由主题 chrome 内的 .cm-yaml-* 着色 (!important 覆盖 content 基色)。
import { EditorView, Decoration, ViewPlugin } from '@codemirror/view'
import { HighlightStyle, syntaxHighlighting, syntaxTree } from '@codemirror/language'
import { RangeSetBuilder } from '@codemirror/state'
import { tags as t } from '@lezer/highlight'

// ---- VS Code Dark+ ----
const darkChrome = EditorView.theme(
  {
    // chrome (背景/前景/行号) 走壳层 CSS 变量, 与面板同面; 语法色保持 VS Code 色板不动
    '&': { color: 'var(--text)', backgroundColor: 'var(--panel)' },
    '.cm-content': { caretColor: '#aeafad' },
    '.cm-cursor, .cm-dropCursor': { borderLeftColor: '#aeafad' },
    '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
      { backgroundColor: '#264f78' },
    '.cm-gutters': { backgroundColor: 'var(--panel)', color: 'var(--muted-soft)', border: 'none' },
    '.cm-activeLine': { backgroundColor: '#ffffff0a' },
    '.cm-activeLineGutter': { backgroundColor: '#ffffff0f', color: '#c6c6c6' },
    '.cm-selectionMatch': { backgroundColor: '#add6ff26' },
    '&.cm-focused .cm-matchingBracket': { backgroundColor: '#0064001a', outline: '1px solid #888' },
    // 未引号标量着色: 文法把它们都归为 content (不上色), 由 scalarHighlighter 按值类型加类, 此处单一来源着色
    '.cm-yaml-string': { color: '#ce9178' },
    '.cm-yaml-number': { color: '#b5cea8' },
    '.cm-yaml-bool': { color: '#569cd6' },
    '.cm-yaml-null': { color: '#569cd6' },
  },
  { dark: true },
)

const darkHighlight = HighlightStyle.define([
  { tag: [t.definition(t.propertyName), t.propertyName], color: '#9cdcfe' },
  { tag: [t.string, t.special(t.string), t.attributeValue], color: '#ce9178' },
  { tag: [t.lineComment, t.comment], color: '#6a9955', fontStyle: 'italic' },
  { tag: [t.separator, t.punctuation, t.squareBracket, t.brace], color: '#d4d4d4' },
  { tag: [t.keyword, t.meta], color: '#569cd6' },
  { tag: t.typeName, color: '#4ec9b0' },
  { tag: t.labelName, color: '#dcdcaa' },
  { tag: t.invalid, color: '#f48771' },
  // ST 追加: 数字绿 / 布尔蓝(同关键字) / 函数调用黄 / 操作符默认色
  { tag: t.number, color: '#b5cea8' },
  { tag: t.bool, color: '#569cd6' },
  { tag: t.function(t.variableName), color: '#dcdcaa' },
  { tag: t.operator, color: '#d4d4d4' },
])

// ---- VS Code Light+ ----
const lightChrome = EditorView.theme(
  {
    // chrome 走壳层 CSS 变量 (白底本就等于 --panel, 变量化防漂移); 语法色保持 VS Code 色板不动
    '&': { color: 'var(--text)', backgroundColor: 'var(--panel)' },
    '.cm-content': { caretColor: '#000000' },
    '.cm-cursor, .cm-dropCursor': { borderLeftColor: '#000000' },
    '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection':
      { backgroundColor: '#add6ff' },
    '.cm-gutters': { backgroundColor: 'var(--panel)', color: 'var(--muted-soft)', border: 'none' },
    '.cm-activeLine': { backgroundColor: '#00000008' },
    '.cm-activeLineGutter': { backgroundColor: '#0000000f', color: '#0b216f' },
    '.cm-selectionMatch': { backgroundColor: '#a8ac9426' },
    '&.cm-focused .cm-matchingBracket': { backgroundColor: '#0064001a', outline: '1px solid #aaa' },
    '.cm-yaml-string': { color: '#a31515' },
    '.cm-yaml-number': { color: '#098658' },
    '.cm-yaml-bool': { color: '#0000ff' },
    '.cm-yaml-null': { color: '#0000ff' },
  },
  { dark: false },
)

const lightHighlight = HighlightStyle.define([
  { tag: [t.definition(t.propertyName), t.propertyName], color: '#0451a5' },
  { tag: [t.string, t.special(t.string), t.attributeValue], color: '#a31515' },
  { tag: [t.lineComment, t.comment], color: '#008000', fontStyle: 'italic' },
  { tag: [t.separator, t.punctuation, t.squareBracket, t.brace], color: '#000000' },
  { tag: [t.keyword, t.meta], color: '#0000ff' },
  { tag: t.typeName, color: '#267f99' },
  { tag: t.labelName, color: '#795e26' },
  { tag: t.invalid, color: '#cd3131' },
  // ST 追加: 数字绿 / 布尔蓝(同关键字) / 函数调用棕 / 操作符默认色
  { tag: t.number, color: '#098658' },
  { tag: t.bool, color: '#0000ff' },
  { tag: t.function(t.variableName), color: '#795e26' },
  { tag: t.operator, color: '#000000' },
])

// 主题扩展 (供 CodeEditor 经 Compartment 热切): chrome + 语法高亮
export const darkExt = [darkChrome, syntaxHighlighting(darkHighlight)]
export const lightExt = [lightChrome, syntaxHighlighting(lightHighlight)]

// ---- 标量识别装饰插件: 给"值"Literal 中的 数字/布尔/null 加类 (文法把它们都归为 content) ----
// 正则与 YAML 1.1/1.2 常见写法对齐 (含 0x/0o/.inf/.nan, yes/no/on/off, ~)。
const NUMBER_RE = /^[+-]?(?:0x[0-9a-fA-F]+|0o[0-7]+|(?:\d[\d_]*)?\.?\d[\d_]*(?:[eE][+-]?\d+)?|\.inf|\.nan)$/
const BOOL_RE = /^(?:true|false|True|False|TRUE|FALSE|yes|no|Yes|No|YES|NO|on|off|On|Off|ON|OFF)$/
const NULL_RE = /^(?:null|Null|NULL|~)$/

const stringMark = Decoration.mark({ class: 'cm-yaml-string' })
const numberMark = Decoration.mark({ class: 'cm-yaml-number' })
const boolMark = Decoration.mark({ class: 'cm-yaml-bool' })
const nullMark = Decoration.mark({ class: 'cm-yaml-null' })

function buildScalarDecos(view) {
  const builder = new RangeSetBuilder()
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(view.state).iterate({
      from,
      to,
      enter: (node) => {
        if (node.name !== 'Literal' || node.to <= node.from) return
        const parent = node.node.parent
        if (parent && parent.name === 'Key') return // 跳过键, 只染值
        const text = view.state.doc.sliceString(node.from, node.to)
        // 文法未给值类型区分 → 按文本判定; 缺省按字符串 (单一来源, 无 highlightStyle 竞争 content)
        let mark = stringMark
        if (NUMBER_RE.test(text)) mark = numberMark
        else if (BOOL_RE.test(text)) mark = boolMark
        else if (NULL_RE.test(text)) mark = nullMark
        builder.add(node.from, node.to, mark)
      },
    })
  }
  return builder.finish()
}

export const scalarHighlighter = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.decorations = buildScalarDecos(view)
    }
    update(u) {
      if (u.docChanged || u.viewportChanged) this.decorations = buildScalarDecos(u.view)
    }
  },
  { decorations: (v) => v.decorations },
)
