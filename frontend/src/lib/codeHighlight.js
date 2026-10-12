const KEYWORDS = new Set(`
  and as assert async await break case catch class const continue def default del do elif else
  except export extends false finally for from function global if import in instanceof interface
  is lambda let new nonlocal not null of or pass raise return self static super switch this
  throw true try type typeof undefined var void while with yield None True False print
  public private protected readonly abstract implements package enum namespace declare
  none true false
  select insert update delete create table where join left right inner outer on group by order
  having limit offset distinct union into values set primary key foreign references not null
  int float str bool list dict tuple set bytes object number string boolean any unknown
  echo fi then done esac local readonly sudo pip npm npx
`.trim().split(/\s+/))

const BUILTINS = new Set(`
  print len range enumerate zip map filter sum min max open input isinstance
  console Math JSON Promise Array Object String Number Boolean Date Error
  document window setTimeout fetch require module process
`.trim().split(/\s+/))

export function normalizeCodeLanguage(value) {
  const language = String(value || '').trim().toLowerCase()
  const aliases = {
    py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    sh: 'bash', shell: 'bash', zsh: 'bash', yml: 'yaml', html: 'html', xml: 'xml',
    md: 'markdown', csharp: 'c#', cs: 'c#', cpp: 'c++'
  }
  return aliases[language] || language || 'text'
}

function escapeHtml(value) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

function token(className, value) {
  return `<span class="code-token-${className}">${escapeHtml(value)}</span>`
}

export function highlightCode(source, language = '') {
  const code = String(source || '')
  const kind = normalizeCodeLanguage(language)
  if (kind === 'text' || kind === 'plaintext') return escapeHtml(code)

  const hashComments = /^(python|bash|yaml|ruby|toml|powershell)$/.test(kind)
  const dashComments = kind === 'sql'
  let output = ''
  let index = 0

  while (index < code.length) {
    const rest = code.slice(index)
    let match
    let category = ''

    if (rest.startsWith('/*')) {
      match = rest.match(/^\/\*[\s\S]*?(?:\*\/|$)/)?.[0]
      category = 'comment'
    } else if (rest.startsWith('<!--')) {
      match = rest.match(/^<!--[\s\S]*?(?:-->|$)/)?.[0]
      category = 'comment'
    } else if ((hashComments && rest.startsWith('#')) || (!hashComments && !dashComments && rest.startsWith('//')) || (dashComments && rest.startsWith('--'))) {
      match = rest.match(/^[^\n]*/)?.[0]
      category = 'comment'
    } else if (kind === 'python' && (rest.startsWith("'''") || rest.startsWith('"""'))) {
      const quote = rest.slice(0, 3)
      const end = rest.indexOf(quote, 3)
      match = end < 0 ? rest : rest.slice(0, end + 3)
      category = 'string'
    } else if (/^['"`]/.test(rest)) {
      const quote = rest[0]
      let end = 1
      while (end < rest.length) {
        if (rest[end] === '\\') { end += 2; continue }
        if (rest[end++] === quote) break
      }
      match = rest.slice(0, end)
      category = 'string'
    } else if ((match = rest.match(/^\b(?:0x[\da-fA-F]+|\d+(?:\.\d+)?)\b/)?.[0])) {
      category = 'number'
    } else if ((match = rest.match(/^@[A-Za-z_][\w.]*/)?.[0])) {
      category = 'decorator'
    } else if ((match = rest.match(/^[A-Za-z_$][\w$]*/)?.[0])) {
      if ((kind === 'html' || kind === 'xml') && /<\/?$/.test(code.slice(0, index))) category = 'keyword'
      else if (KEYWORDS.has(match.toLowerCase())) category = 'keyword'
      else if (BUILTINS.has(match)) category = 'builtin'
      else if (/^\s*\(/.test(rest.slice(match.length))) category = 'function'
      else if (/^[A-Z][A-Za-z\d_]*$/.test(match)) category = 'type'
      else if ((kind === 'html' || kind === 'xml') && /^\s*=/.test(rest.slice(match.length))) category = 'property'
      else if (/^\s*:/.test(rest.slice(match.length)) && (kind === 'json' || kind === 'yaml')) category = 'property'
    } else {
      match = rest[0]
    }

    output += category ? token(category, match) : escapeHtml(match)
    index += match.length
  }
  return output
}
