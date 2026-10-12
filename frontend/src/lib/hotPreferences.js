export const HOT_TOPICS = ['大模型与AI', '智能体与编程', '科技与产品', '产业与商业', '研究与论文', '安全与政策']
const TOPIC_WORDS = {
  '大模型与AI': ['AI', '人工智能', '模型', 'OpenAI', 'DeepSeek', 'Claude', 'Qwen', 'LLM'],
  '智能体与编程': ['Agent', '智能体', '编程', '代码', 'MCP', 'Codex', '工具', '工作流'],
  '科技与产品': ['科技', '产品', '发布', '芯片', '机器人', '硬件', '应用'],
  '产业与商业': ['产业', '商业', '融资', '公司', '市场', '投资', '收入'],
  '研究与论文': ['研究', '论文', '报告', '学术', '训练', '评测', 'benchmark'],
  '安全与政策': ['安全', '政策', '监管', '版权', '隐私', '攻击', '泄露', '风险']
}
export const defaultHotPreferences = () => ({ direction: '', maxItems: 30 })
export function filterHotCandidates(rows, preferences, now = Date.now()) {
  const words = [...(preferences.topics || []).flatMap(topic => TOPIC_WORDS[topic] || [topic]),
    ...(preferences.keywords || preferences.direction || '').split(/[,，;；\n]/)].map(word => word.trim().toLowerCase()).filter(Boolean)
  const cutoff = now - (preferences.lookbackDays || 7) * 86400000
  const seen = new Set()
  return rows.filter(item => {
    const stamp = Date.parse(item.latestAt || item.publishedAt || item.reportDate || '')
    if (Number.isFinite(stamp) && stamp < cutoff) return false
    const text = [item.title, item.summary, item.latest, ...(item.attention?.domains || []).map(domain => domain.label)].join(' ').toLowerCase()
    if (words.length && !words.some(word => text.includes(word))) return false
    const key = `${item.kind}:${item.id}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
