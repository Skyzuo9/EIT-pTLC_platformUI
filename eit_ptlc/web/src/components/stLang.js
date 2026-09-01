// CodeMirror 6 结构化文本 (ST / IEC 61131-3) 语言: 用 StreamLanguage 流式分词,
// 发射 @lezer/highlight 标准 tag (经 tokenTable 显式绑定), 由 cmTheme.js 的 HighlightStyle 按 tag 上色。
//
// 文法事实 (CODESYS ST): 关键字大小写不敏感; 块注释 (* ... *) 可跨行; 行注释 //; 字符串 '...' / "..."
// 以 $ 为转义符; 数字含十进制/实数、进制 16#FF/8#/2#、时间日期字面量 T#/D#/DT#/TOD# 等。
// 标识符紧跟 '(' 视为函数/功能块调用 (黄色), 其余标识符保持默认文本色。
import { StreamLanguage } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

// ---- 关键字 (全大写存储, 比对时把当前词转大写) ----
const KEYWORDS = new Set([
  'IF', 'THEN', 'ELSIF', 'ELSE', 'END_IF',
  'CASE', 'OF', 'END_CASE',
  'FOR', 'TO', 'BY', 'DO', 'END_FOR',
  'WHILE', 'END_WHILE',
  'REPEAT', 'UNTIL', 'END_REPEAT',
  'RETURN', 'EXIT', 'CONTINUE', 'JMP',
  'FUNCTION', 'END_FUNCTION',
  'FUNCTION_BLOCK', 'END_FUNCTION_BLOCK',
  'METHOD', 'END_METHOD',
  'PROGRAM', 'END_PROGRAM',
  'ACTION', 'END_ACTION',
  'PROPERTY', 'END_PROPERTY',
  'VAR', 'VAR_INPUT', 'VAR_OUTPUT', 'VAR_IN_OUT', 'VAR_GLOBAL',
  'VAR_TEMP', 'VAR_STAT', 'VAR_EXTERNAL', 'VAR_CONFIG', 'VAR_ACCESS',
  'CONSTANT', 'RETAIN', 'PERSISTENT', 'NON_RETAIN', 'END_VAR',
  'TYPE', 'END_TYPE', 'STRUCT', 'END_STRUCT', 'UNION', 'END_UNION',
  'ARRAY', 'POINTER', 'REF_TO', 'REFERENCE', 'AT',
  'AND', 'OR', 'XOR', 'NOT', 'MOD',
  'THIS', 'SUPER', 'ADR', 'SIZEOF',
])

// ---- 类型名 (含常用功能块) ----
const TYPES = new Set([
  'BOOL', 'BYTE', 'WORD', 'DWORD', 'LWORD',
  'SINT', 'INT', 'DINT', 'LINT',
  'USINT', 'UINT', 'UDINT', 'ULINT',
  'REAL', 'LREAL',
  'TIME', 'LTIME', 'DATE', 'TIME_OF_DAY', 'TOD', 'DATE_AND_TIME', 'DT',
  'STRING', 'WSTRING', 'CHAR', 'WCHAR',
  'TON', 'TOF', 'TP', 'CTU', 'CTD', 'CTUD', 'R_TRIG', 'F_TRIG', 'RS', 'SR',
])

// 时间/日期字面量前缀 (后跟 # 与数值): T#10ms / TIME#1s / D#2024-01-01 / DT#... / TOD#...
const TIME_LITERAL_RE = /^(?:LTIME|TIME|LT|T|DATE|DT|TOD|D)#[0-9a-zA-Z_.:+-]+/i

function token(stream, state) {
  // 块注释续行: 找到 *) 收尾, 否则吃到行尾保持 inComment
  if (state.inComment) {
    if (stream.skipTo('*)')) {
      stream.match('*)')
      state.inComment = false
    } else {
      stream.skipToEnd()
    }
    return 'comment'
  }

  // 空白
  if (stream.eatSpace()) {
    return null
  }

  // 行注释 //
  if (stream.match('//')) {
    stream.skipToEnd()
    return 'comment'
  }

  // 块注释起始 (*
  if (stream.match('(*')) {
    if (stream.skipTo('*)')) {
      stream.match('*)')
    } else {
      stream.skipToEnd()
      state.inComment = true
    }
    return 'comment'
  }

  // 字符串 '...' / "..." (ST 以 $ 为转义符)
  const quote = stream.peek()
  if (quote === '"' || quote === "'") {
    stream.next()
    let escaped = false
    let ch
    while ((ch = stream.next()) != null) {
      if (ch === quote && !escaped) {
        break
      }
      escaped = ch === '$' && !escaped
    }
    return 'string'
  }

  // 时间/日期字面量 (须在普通数字之前判, 因以字母前缀开头)
  if (stream.match(TIME_LITERAL_RE)) {
    return 'number'
  }

  // 进制字面量 2#/8#/16#
  if (stream.match(/^\d+#[0-9a-fA-F_]+/)) {
    return 'number'
  }

  // 十进制 / 实数 / 指数
  if (stream.match(/^\d[\d_]*\.?[\d_]*(?:[eE][+-]?\d+)?/)) {
    return 'number'
  }
  if (stream.match(/^\.\d[\d_]*(?:[eE][+-]?\d+)?/)) {
    return 'number'
  }

  // 标识符 -> 关键字 / 类型 / 布尔 / 函数调用 / 普通变量
  if (stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)) {
    const word = stream.current().toUpperCase()
    if (KEYWORDS.has(word)) {
      return 'keyword'
    }
    if (TYPES.has(word)) {
      return 'typeName'
    }
    if (word === 'TRUE' || word === 'FALSE') {
      return 'bool'
    }
    // 标识符紧跟 '(' 视为调用 (功能块/函数)
    if (stream.peek() === '(') {
      return 'function'
    }
    return 'variableName'
  }

  // 操作符 / 标点
  if (stream.match(/^(?::=|<>|<=|>=|=>|\*\*|[-+*/<>=&;,.:()[\]{}^])/)) {
    return 'operator'
  }

  // 兜底: 吞一个字符防止卡死
  stream.next()
  return null
}

// tokenTable: 把 token() 返回名显式绑定到 @lezer/highlight tag (不依赖默认映射)
export const stLanguage = StreamLanguage.define({
  name: 'iec-st',
  startState() {
    return { inComment: false }
  },
  token,
  languageData: {
    commentTokens: { line: '//', block: { open: '(*', close: '*)' } },
  },
  tokenTable: {
    keyword: t.keyword,
    comment: t.comment,
    string: t.string,
    number: t.number,
    typeName: t.typeName,
    bool: t.bool,
    operator: t.operator,
    function: t.function(t.variableName),
    variableName: t.variableName,
  },
})
