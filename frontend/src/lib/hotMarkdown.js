const escapeLabel = value => String(value || '').replace(/[\\`*_[\]<>]/g, '\\$&').replace(/\r?\n/g, ' ')

export function hotMarkdownFile(item, body = item.body || '') {
  const title = String(item.title || '热点新闻').replace(/\r?\n/g, ' ').trim()
  const lines = [`# ${escapeLabel(title)}`, '', '## 摘要', '', item.summary?.trim() || '暂无摘要', '', '## 完整内容', '', body.trim() || '来源暂未提供完整内容。', '', '## 原始来源', '']
  const raw = item.data?.sources?.length ? item.data.sources : [{url:item.data?.sourceUrl,title:'原始来源'}]
  const seen = new Set()
  for (const source of raw) {
    try {
      const url = new URL(source.url)
      if (!['http:', 'https:'].includes(url.protocol) || seen.has(url.href)) continue
      seen.add(url.href)
      lines.push(`- [${escapeLabel(source.title || url.hostname)}](<${url.href.replace(/</g,'%3C').replace(/>/g,'%3E')}>)`)
    } catch { /* Ignore invalid source URLs. */ }
  }
  if (!seen.size) lines.push('暂无原始来源链接。')
  if (item.data?.publishedAt) lines.push('', `发布时间：${escapeLabel(item.data.publishedAt)}`)
  if (item.data?.source === 'hot-agent') lines.push('', '> 本文基于联网搜索返回的来源内容整理，可通过原始来源核对。')
  const filename = title.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'_').replace(/[. ]+$/g,'').slice(0,120) || '热点新闻'
  return new File([lines.join('\n')+'\n'], filename+'.md', {type:'text/markdown;charset=utf-8'})
}
