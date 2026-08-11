function escapeHtml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function inlineMarkdown(value) {
  const tokens = []
  const protect = (html) => {
    const token = `\u0000${tokens.length}\u0000`
    tokens.push(html)
    return token
  }

  let output = escapeHtml(value)
  output = output.replace(/`([^`\n]+)`/g, (_, code) => protect(`<code>${code}</code>`))
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => (
    protect(`<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`)
  ))
  output = output.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  output = output.replace(/__([^_\n]+)__/g, '<strong>$1</strong>')
  output = output.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>')
  output = output.replace(/(?<!_)_([^_\n]+)_(?!_)/g, '<em>$1</em>')
  return output.replace(/\u0000(\d+)\u0000/g, (_, index) => tokens[Number(index)])
}

export function renderMarkdown(source = '') {
  const lines = String(source).replace(/\r\n?/g, '\n').split('\n')
  const output = []
  let paragraph = []
  let listType = ''
  let inCode = false
  let codeLanguage = ''
  let codeLines = []

  const closeList = () => {
    if (listType) output.push(`</${listType}>`)
    listType = ''
  }
  const flushParagraph = () => {
    if (!paragraph.length) return
    output.push(`<p>${inlineMarkdown(paragraph.join('\n')).replaceAll('\n', '<br>')}</p>`)
    paragraph = []
  }
  const flushCode = () => {
    const language = codeLanguage ? ` class="language-${escapeHtml(codeLanguage)}"` : ''
    output.push(`<pre><code${language}>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
    codeLines = []
    codeLanguage = ''
  }

  for (const line of lines) {
    const fence = line.match(/^\s*```\s*([\w-]*)\s*$/)
    if (fence) {
      if (inCode) flushCode()
      else {
        flushParagraph()
        closeList()
        codeLanguage = fence[1]
      }
      inCode = !inCode
      continue
    }
    if (inCode) {
      codeLines.push(line)
      continue
    }

    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/)
    const unordered = line.match(/^\s*[-+*]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)
    const quote = line.match(/^\s*>\s?(.*)$/)

    if (!line.trim()) {
      flushParagraph()
      closeList()
    } else if (heading) {
      flushParagraph(); closeList()
      const level = heading[1].length
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`)
    } else if (unordered || ordered) {
      flushParagraph()
      const nextType = unordered ? 'ul' : 'ol'
      if (listType !== nextType) { closeList(); output.push(`<${nextType}>`); listType = nextType }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`)
    } else if (quote) {
      flushParagraph(); closeList()
      output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`)
    } else if (/^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(line)) {
      flushParagraph(); closeList(); output.push('<hr>')
    } else {
      paragraph.push(line)
    }
  }

  if (inCode) flushCode()
  flushParagraph()
  closeList()
  return output.join('')
}
