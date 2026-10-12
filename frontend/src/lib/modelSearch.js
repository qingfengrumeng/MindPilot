const normalize = value => String(value ?? '').normalize('NFKC').toLowerCase().replace(/[\s_./-]+/g, '')

export function matchesModelSearch(name, query) {
  const target = normalize(name)
  return String(query ?? '').trim().split(/\s+/).every(part => {
    const needle = normalize(part)
    let index = 0
    for (const character of target) if (character === needle[index]) index++
    return index === needle.length
  })
}
