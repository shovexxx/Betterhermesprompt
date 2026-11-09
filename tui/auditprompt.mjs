/**
 * auditprompt — BetterPrompt TUI widget.
 * /auditprompt <your prompt>  ·  pre-audits a draft in the dock.
 * Standalone (no imports), deterministic, zero tokens.
 */
export default function register(sdk) {
  const { Box, Text, Dialog, defineWidgetApp, h } = sdk

  const TYPO = { teh: 'the', recieve: 'receive', seperate: 'separate', definately: 'definitely',
    occured: 'occurred', untill: 'until', wich: 'which', taht: 'that', hte: 'the',
    becuase: 'because', thier: 'their', dont: "don't", cant: "can't", wont: "won't",
    doesn: "doesn't", isnt: "isn't", promp: 'prompt', prommpt: 'prompt' }
  const FILLER = ['basically', 'sort of', 'you know', 'i just', 'just a quick', 'as you know', 'please note', 'and stuff', 'so basically']
  const VAGUE = ['make it better', 'fix it', 'do it right', 'somehow', 'whatever', 'stuff', 'things']

  function audit(text) {
    const t = (text || '').trim()
    const low = t.toLowerCase()
    const issues = []
    for (const [w, f] of Object.entries(TYPO))
      if (f && new RegExp('\\b' + w + '\\b', 'i').test(t)) issues.push(`"${w}" → "${f}"`)
    for (const f of FILLER) if (low.includes(f)) issues.push(`filler: "${f}"`)
    if (/(please\s+please|\bdelete\b[\s\S]*\bkeep it\b)/.test(low)) issues.push('repeated / contradictory ask')
    for (const v of VAGUE) if (low.includes(v)) issues.push(`ambiguous: "${v}"`)
    if (!/@\S+|in \S+|\/\S+/.test(t)) issues.push('no input/location context')
    if (!/output|result|return|format|json|md/.test(low)) issues.push('no expected output format')
    const len = t.length || 0
    const tok = Math.max(1, Math.round(Math.max(len / 4, (t.match(/\S+/g) || []).length * 1.35)))
    const penalty = issues.length * 6
    const score = t ? Math.max(0, Math.min(100, 100 - penalty)) : 0
    return { score, tok, issues, text: t }
  }

  defineWidgetApp({
    id: 'auditprompt',
    help: 'pre-audit a prompt — tokens, typos, rambling, clarity (BetterPrompt)',
    mode: 'ambient',
    init: arg => ({ text: (arg || '').trim() }),
    render: ({ state, t }) => {
      if (!state.text) return h(Dialog, { width: 44 }, h(Text, { color: t.color.muted }, '⌀ auditprompt — pass a prompt:  /auditprompt <your prompt>'))
      const r = audit(state.text)
      const color = r.score >= 75 ? t.color.ok : r.score >= 55 ? t.color.label : t.color.error
      const rows = [
        h(Box, { flexDirection: 'row', gap: 1 }, [
          h(Text, { color, bold: true }, `score ${String(r.score).padStart(3)}/100`),
          h(Text, { color: t.color.muted }, `  ${String(r.tok).padStart(4)} tok`),
        ]),
      ]
      if (r.issues.length) rows.push(h(Text, { color: t.color.muted }, r.issues.slice(0, 4).map(i => '• ' + i).join('\n')))
      else rows.push(h(Text, { color: t.color.ok }, 'clean'))
      return h(Dialog, { width: 44, title: `BetterPrompt · ${state.text.length > 40 ? state.text.slice(0, 40) + '…' : state.text}` }, ...rows)
    },
  })
}
