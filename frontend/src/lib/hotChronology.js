export function sortHotByPublished(items) {
  const timestamp = item => {
    const published = Date.parse(item.data?.publishedAt || '')
    if(Number.isFinite(published)) return published
    const created = Date.parse(item.createdAt || '')
    return Number.isFinite(created) ? created : 0
  }
  return [...items].sort((a,b)=>timestamp(b)-timestamp(a))
}
