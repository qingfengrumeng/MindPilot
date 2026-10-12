/** Plain summary text without the web citation badges used in chat messages. */
export function summaryText(value) {
  return String(value || '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[〔【\[]\s*网页\s*\d+\s*[〕】\]]/g, '')
    .replace(/[*_`#>]+/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s+([，。；：！？、])/g, '$1')
    .trim()
}
