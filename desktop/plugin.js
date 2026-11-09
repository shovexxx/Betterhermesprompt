/**
 * better-prompt — the second prompt bar.
 *
 * A live audit strip rendered directly below the composer (COMPOSER_AREAS.underside):
 * it watches the draft you type in the MAIN bar, scores it, estimates tokens,
 * catches typos + mistyped commands, flags rambling / wasted loops, suggests the
 * missing context, and can Rewrite (local, 0 tokens) / Send improved straight back
 * into the composer via host.composer. A toggle in COMPOSER_AREAS.actions turns the
 * live audit on/off, and an OPT-IN composer.middleware fixes high-confidence typos
 * and mistyped slash commands the moment you hit send.
 *
 * All analysis is deterministic and runs in-page. The richer AI polish lives in the
 * CLI / slash command (/bhp-rewrite); this bar drops that command into the composer
 * so you can run it when you want it.
 */

import {
  host,
  haptic,
  useValue,
  COMPOSER_AREAS,
  PALETTE_AREA,
  STATUSBAR_AREAS,
  Switch,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter
} from '@hermes/plugin-sdk'
import { useState, useEffect, useRef } from 'react'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

// -------------------------------------------------------------- engine (JS)
const TYPO = {
  teh: 'the', recieve: 'receive', seperate: 'separate', definately: 'definitely',
  occured: 'occurred', untill: 'until', wich: 'which', taht: 'that', hte: 'the',
  becuase: 'because', thier: 'their', dont: "don't", cant: "can't", wont: "won't",
  doesnt: "doesn't", isnt: "isn't", promp: 'prompt', prommpt: 'prompt', pls: '', plz: ''
}
const CMDS = ['memory','remember','forget','skills','tools','model','setup','config',
  'skin','theme','tldr','loop','heartbeat','status','doctor','clear','compact','usage',
  'cost','plugins','mcp','cron','help','exit','quit','new','continue','resume','undo',
  'retry','edit','project','chat','cd','pwd','ls','cat','show','browse','summarize','review']
const FILLER = ['basically','sort of','you know','i just','just a quick','as you know',
  'please note','and stuff','etc etc','so basically','right now','i wanna','gonna']
const VAGUE = ['make it better','fix it','do it right','somehow','whatever','etc','stuff',
  'things','the usual','and so on']
const TEMPLATES = [
  { name: 'Code', kw: ['write','build','implement','refactor','script','python','api','fix the bug','add feature'] },
  { name: 'Research', kw: ['research','explain','what is','how does','compare','learn about','summary'] },
  { name: 'Writing', kw: ['email','blog','post','tweet','draft','essay','reply','copy'] },
  { name: 'Debug', kw: ['error','crashes','not working','fails','traceback','why is'] },
  { name: 'Plan', kw: ['plan','outline','design','architecture','roadmap','strategy','blueprint'] },
  { name: 'Review', kw: ['review','assess','audit','critique','evaluate','risk','compare'] }
]
const tokens = t => t ? Math.max(1, Math.round(Math.max(t.length / 4, (t.match(/\S+/g) || []).length * 1.35))) : 0

function audit(text) {
  const t = (text || '').trim()
  const issues = []
  const low = t.toLowerCase()
  for (const [w, f] of Object.entries(TYPO))
    if (f && new RegExp('\\b' + w + '\\b', 'i').test(t)) issues.push({ sev: 'medium', kind: 'spelling', msg: `"${w}" → "${f}"` })
  for (const c of (t.match(/\/(\w+)\b/g) || []))
    if (!CMDS.includes(c.slice(1))) issues.push({ sev: 'medium', kind: 'command', msg: `Unknown / mistyped command ${c}` })
  const hits = FILLER.filter(f => low.includes(f))
  if (hits.length) issues.push({ sev: 'medium', kind: 'filler', msg: `Filler: ${hits.slice(0, 4).join(', ')}` })
  if (/(please\s+please|\bdelete\b[\s\S]*\bkeep it\b)/.test(low)) issues.push({ sev: 'high', kind: 'redundancy', msg: 'Repeated / contradictory ask — state the intent once.' })
  const vag = VAGUE.filter(v => low.includes(v))
  if (vag.length) issues.push({ sev: 'medium', kind: 'vague', msg: `Ambiguous: ${vag.slice(0, 3).join(', ')}` })
  if (!/output|result|return|format|json|md|csv|table|report/.test(low)) issues.push({ sev: 'medium', kind: 'output', msg: 'No expected output format.' })
  if (!/limit|only|don't|must not|require|constraint|unless|except/.test(low)) issues.push({ sev: 'low', kind: 'constraint', msg: 'No constraints given.' })
  if (t && t.length < 6) issues.push({ sev: 'high', kind: 'short', msg: 'Nearly empty prompt.' })

  const penalty = issues.reduce((s, i) => s + ({ high: 20, medium: 9, low: 3 })[i.sev], 0)
  const score = t ? Math.max(0, Math.min(100, 100 - penalty)) : 0
  const grade = score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 55 ? 'C' : 'D'

  let tpl = 'General', bestk = 0
  for (const tm of TEMPLATES) { const k = tm.kw.filter(k => low.includes(k)).length; if (k > bestk) { tpl = tm.name; bestk = k } }

  let rf = t
  for (const [w, f] of Object.entries(TYPO)) if (f) rf = rf.replace(new RegExp('\\b' + w + '\\b', 'ig'), f)
  for (const f of FILLER) if (f) rf = rf.replace(new RegExp('\\b' + f + '\\b\\s*,?\\s*', 'ig'), ' ')
  rf = rf.replace(/\s{2,}/g, ' ').replace(/\b(\w+)\s+\1\b/g, '$1').trim()

  return { score, grade, tokens: tokens(t), issues, template: tpl, rebuilded: rf || t, cost: (tokens(t) / 1e6) * 1.0 }
}

// -------------------------------------------------------------- offline editor (local, no backend)
const PLAN_SUGGESTIONS = [
  ['Plan it together', 'Let\'s plan "{topic}" together. Start by asking me the 2-3 most important questions, then propose a step-by-step plan I can approve before you build.'],
  ['Smallest version first', 'We\'re making "{topic}". Propose the smallest playable/useful version first, list what you would cut for v1, then ask what to keep.'],
  ['Options + recommendation', 'For "{topic}": give me 2-3 concrete options, compare them briefly, and recommend one with a reason.'],
  ['Ask me first', 'Before working on "{topic}", ask me the questions that would change the approach the most — then act on my answers.']
]
function suggestOffline(text) {
  const t = (text || '').trim()
  if (!t || t.split(/\s+/).length > 16) return []
  const topic = t.replace(/[.!?]+$/, '').trim()
  return PLAN_SUGGESTIONS.map(([title, p]) => ({ title, prompt: p.replace('{topic}', topic) }))
}
function levDist(a, b) {
  if (a === b) return 0
  if (!a.length) return b.length
  if (!b.length) return a.length
  const p = Array.from({ length: b.length + 1 }, (_, j) => j)
  for (let i = 0; i < a.length; i++) {
    let up = i + 1, diag = i
    for (let j = 0; j < b.length; j++) {
      const next = p[j + 1]
      up = Math.min(p[j + 1] + 1, up + 1, diag + (a[i] !== b[j] ? 1 : 0))
      p[j + 1] = up; diag = next
    }
  }
  return p[b.length]
}
function splitRunon(s) {
  const words = s.split(/\s+/)
  const n = words.length
  if (n <= 40) return [s]
  const target = Math.floor(n / 2)
  let cands = []
  for (let i = 1; i < n; i++)
    if (['and', 'but', 'then', 'so', 'however'].includes(words[i].toLowerCase()) || /[,;]$/.test(words[i - 1])) cands.push(i)
  if (!cands.length) return [s]
  const best = cands.reduce((x, y) => Math.abs(x - target) < Math.abs(y - target) ? x : y)
  let a = words.slice(0, best).join(' ').replace(/(?:[,;])+$/, '').replace(/\s+(and|but|then|so|,)\s*$/i, '').trim()
  let b = words.slice(best).join(' ').trim()
  if (a && !/[.!?]$/.test(a)) a += '.'
  if (b && /^[a-z]/.test(b)) b = b[0].toUpperCase() + b.slice(1)
  return b ? [a, b] : [a]
}

function offlineEdit(text) {
  const t0 = (text || '').trim()
  const ch = { typos: [], suspect: [], filler: [], runons: 0, grammar: 0, structure: false }
  const before = t0 ? audit(t0).score : 0
  if (!t0) return { improved: '', changes: ch, score_before: 0, score_after: 0, suggestions: [] }
  let t = t0
  if (/^[a-z]/.test(t[0])) { t = t[0].toUpperCase() + t.slice(1); ch.grammar++ }
  let t2 = t.replace(/\bi\b/g, 'I'); if (t2 !== t) { ch.grammar++; t = t2 }
  for (const [w, f] of Object.entries(TYPO)) {
    if (!f) continue
    if (new RegExp('\\b' + w + '\\b', 'ig').test(t)) { t = t.replace(new RegExp('\\b' + w + '\\b', 'ig'), f); ch.typos.push(w + '→' + f) }
  }
  for (const w of (t.match(/[A-Za-z0-9']+/g) || []))
    if (/\d/.test(w) && /[a-z]/.test(w) && w.length <= 12 && !ch.suspect.includes(w)) ch.suspect.push(w)
  for (const s of new Set((t.match(/\/([a-z]+)\b/gi) || []).map(x => x.slice(1).toLowerCase()))) {
    if (!CMDS.includes(s)) {
      const cand = CMDS.reduce((a, c) => levDist(s, c) < levDist(s, a) ? c : a, CMDS[0])
      if (cand && cand !== s && levDist(s, cand) <= 2) { t = t.replace(new RegExp('/' + s + '\\b', 'ig'), '/' + cand); ch.typos.push('/' + s + '→/' + cand) }
    }
  }
  for (const f of FILLER) {
    if (!f) continue
    if (new RegExp('\\b' + f + '\\b', 'ig').test(t)) { t = t.replace(new RegExp('\\b' + f + '\\b\\s*,?\\s?', 'ig'), ' '); ch.filler.push(f) }
  }
  let nt = t.replace(/\b(\w+)\s+\1\b/g, '$1'); if (nt !== t) { ch.grammar++; t = nt }
  t = t.replace(/\s{2,}/g, ' ').trim()
  if (/^(want|wanna|need|need to)\b/i.test(t) && !/^I\b/.test(t)) { t = 'I ' + t[0].toLowerCase() + t.slice(1); ch.grammar++ }
  const sents = t.split(/(?<=[.!?])\s+/)
  const rebuilt = []
  for (const s of sents) {
    if (s.split(/\s+/).length > 40) { const parts = splitRunon(s); if (parts.length > 1) { rebuilt.push(...parts); ch.runons += parts.length - 1 } else rebuilt.push(s) }
    else rebuilt.push(s)
  }
  t = rebuilt.join(' ').replace(/\s{2,}/g, ' ').trim()
  if (t && !'!?.'.includes(t[t.length - 1])) { t += '.'; ch.grammar++ }
  // structure framing
  const a2 = audit(t)
  const missing = a2.issues.filter(i => ['input', 'output', 'constraint'].includes(i.kind)).map(i => i.kind)
  const nw = t.split(/\s+/).length
  if (missing.length && !/Goal:|Deliverable:|Quick spec|Done when:|Scope:/.test(t) && nw >= 4 && nw <= 220) {
    const bl = ['', 'Quick spec so one pass is enough:']
    if (missing.includes('input')) bl.push('  Input/scope: <file, repo, URL, or paste the data>')
    if (missing.includes('output')) bl.push('  Output: <what you want back — JSON, code, plan, a file?>')
    if (missing.includes('constraint')) bl.push('  Constraints: <must-nots, size limits, versions>')
    if (bl.length > 1) { t += '\n' + bl.join('\n'); ch.structure = true }
  }
  return { improved: t, changes: ch, score_before: before, score_after: audit(t).score, suggestions: suggestOffline(t0) }
}

// -------------------------------------------------------------- force mode (block sending)
// Module-level so the middleware can read it without render cycles.
let bpEnabled = true
let forceOn = false
let forceReleaseUntil = 0
let forceLastNotice = 0

// -------------------------------------------------------------- audit bar
function AuditBar({ storage, rest }) {
  const sid = useValue(host.state.focusedSessionId)
  const busy = useValue(host.state.busy)
  const [enabled, setEnabled] = useState(storage && storage.get ? storage.get('enabled') !== false : true)
  const [res, setRes] = useState(null)
  const [ai, setAi] = useState(null)      // { loading, kind, improved, questions, model, error }
  const [ftOpen, setFtOpen] = useState(false)
  const [answers, setAnswers] = useState({})
  const [popupOpen, setPopupOpen] = useState(false)
  const [force, setForce] = useState(storage && storage.get ? storage.get('force') === true : false)
  const last = useRef('')
  const cache = useRef(null)

  // keep the module-level flags the middleware reads in sync
  useEffect(() => { bpEnabled = enabled; forceOn = force }, [enabled, force])

  const QS = [
    ['project', 'Project / repo? (language · framework · stack)'],
    ['scope', 'Which files or area?'],
    ['goal', 'Concrete end goal / behaviour you want?'],
    ['output', 'What should the result be? (code, plan, config, doc…)'],
    ['accept', "How will you know it's done?"],
    ['constraints', 'Constraints / must-nots? (versions, limits, security…)'],
    ['extra', 'References or details to include?']
  ]

  useEffect(() => {
    last.current = ''
    setRes(null)
    cache.current = null
    setAi(null)
  }, [sid])

  useEffect(() => {
    if (!enabled) { setRes(null); return }
    const loop = async () => {
      if (busy || !host.composer || !host.composer.getDraft) return
      try {
        const d = (await host.composer.getDraft(sid)) || ''
        if (d !== last.current) {
          last.current = d
          cache.current = audit(d)
          setRes(cache.current)
        }
      } catch (e) { /* pass-through on error */ }
    }
    const id = setInterval(loop, 1400)
    loop()
    return () => clearInterval(id)
  }, [enabled, sid, busy])

  useEffect(() => {
    if (ai && ai.loading) return
    if (!ai || !ai.improved) return
    // keep the live audit in sync if the user types while a suggestion is open
  }, [ai])

  // pop the suggestion into a readable dialog the moment a result lands
  useEffect(() => {
    if (ai && !ai.loading && ai.improved) setPopupOpen(true)
  }, [ai])

  const toggle = (v) => {
    setEnabled(v)
    bpEnabled = v
    if (storage && storage.set) storage.set('enabled', v)
    haptic('tap')
  }
  const toggleForce = (v) => {
    setForce(v)
    forceOn = v
    if (storage && storage.set) storage.set('force', v)
    haptic('tap')
    if (v) host.notify({ kind: 'info', message: 'Force on: Enter won\u2019t send. Click Send or use a BetterPrompt action.' })
  }
  const curModel = () => {
    try { return host.state && host.state.model && typeof host.state.model.get === 'function' ? host.state.model.get() : null } catch (e) { return null }
  }
  const apply = async (txt) => {
    if (!host.composer || !txt) return
    haptic('tap')
    try { await host.composer.setDraft(sid, txt); host.composer.focus(sid); setAi(null); setPopupOpen(false) } catch (e) {}
  }
  const sendImproved = async (txt) => {
    haptic('tap')
    try {
      // plugin's OWN deliberate send: release the force gate for this submit
      forceReleaseUntil = Date.now() + 1000
      await host.composer.setDraft(sid, txt)
      host.composer.submit(sid, txt)
      setAi(null)
      setPopupOpen(false)
    } catch (e) {}
  }
  const runAi = async (kind) => {
    const draft = (await (host.composer && host.composer.getDraft ? host.composer.getDraft(sid) : Promise.resolve(''))) || ''
    if (!draft.trim()) { host.notify({ kind: 'info', message: 'Type something in the prompt bar first.' }); return }
    haptic('tap')
    setAi({ loading: true, kind })
    try {
      const out = await rest('/' + kind, { text: draft, model: curModel() })
      if (out && out.ok) {
        const g = guardImproved(draft, out.improved)
        setAi({ loading: false, kind, draft, improved: g.text, questions: out.questions || [],
                model: out.model || null,
                error: (out.error || null) || (g.reattached ? 'Kept your original ask — the model suggestion had dropped it.' : null),
                fallback: out.fallback })
      } else {
        setAi({ loading: false, kind, draft, improved: (out && out.improved) || draft,
                questions: [], model: null, error: (out && out.error) ? 'AI unavailable — using local rewrite.' : 'No result.', fallback: null })
      }
    } catch (e) {
      setAi({ loading: false, kind, draft, improved: res ? res.rebuilded : draft, questions: [],
              model: null, error: 'AI unavailable — using local rewrite.', fallback: null })
    }
  }

  const setAns = (key, v) => setAnswers(prev => ({ ...prev, [key]: v }))
  const buildFinetune = async () => {
    haptic('tap')
    setFtOpen(false)
    setAi({ loading: true, kind: 'finetune' })
    try {
      const draft2 = (await (host.composer && host.composer.getDraft ? host.composer.getDraft(sid) : Promise.resolve(''))) || ''
      const out = await rest('/finetune', { text: draft2, answers, model: curModel() })
      if (out && out.ok) {
        const g = guardImproved(draft2, out.improved || out.deterministic)
        setAi({ loading: false, kind: 'finetune', draft: draft2, improved: g.text,
                questions: out.questions || [], model: out.model || null,
                error: (out.error || null) || (g.reattached ? 'Kept your original ask — the model suggestion had dropped it.' : null) })
      } else {
        setAi({ loading: false, kind: 'finetune', draft: draft2, improved: (out && out.improved) || (res && res.rebuilded) || '',
                questions: [], model: null, error: (out && out.error) || 'No result.' })
      }
    } catch (e) {
      setAi({ loading: false, kind: 'finetune', draft: draft2, improved: res ? res.rebuilded : '',
              questions: [], model: null, error: 'Fine-tuner unavailable — using local rewrite.' })
    }
  }

  const runOffline = async () => {
    const draft = (await (host.composer && host.composer.getDraft ? host.composer.getDraft(sid) : Promise.resolve(''))) || ''
    if (!draft.trim()) { host.notify({ kind: 'info', message: 'Type something in the prompt bar first.' }); return }
    haptic('tap')
    // fully local + deterministic — no backend, no model, works everywhere
    const r = offlineEdit(draft)
    setAi({ loading: false, kind: 'offline', draft, improved: r.improved || draft,
            questions: [], model: null, error: null,
            changes: r.changes, suggestions: r.suggestions || [],
            scoreBefore: r.score_before, scoreAfter: r.score_after })
  }

  const btn = 'shrink-0 px-2 py-0.5 rounded text-(--ui-accent) hover:bg-(--ui-stroke-secondary) hover:bg-opacity-20'
  const aiBtn = 'shrink-0 px-2 py-0.5 rounded bg-(--ui-accent) text-(--ui-accent-fg) hover:opacity-80'

  return jsxs('div', {
    className: 'flex flex-col px-3 py-1 text-xs border-t border-(--ui-stroke-secondary)',
    children: [
      jsxs('div', { className: 'flex items-center gap-2',
        children: [
          jsx(Tip, { tip: 'Toggle BetterPrompt live audit', children: jsxs('label', { className: 'flex items-center gap-1.5 cursor-pointer select-none shrink-0 text-(--ui-text-secondary)',
            children: [
              jsx(Switch, { checked: enabled, onCheckedChange: toggle, 'aria-label': 'Toggle BetterPrompt live audit' }),
              jsx('span', { className: 'font-medium', children: 'BetterPrompt' })
            ] }) }),
          (enabled && res) && jsx(Tip, { tip: 'Block sending until you use a BetterPrompt action (Offline · polish · Generate · Fine-tune)', children: jsxs('label', {
            className: 'flex items-center gap-1.5 cursor-pointer select-none shrink-0 text-(--ui-text-secondary)',
            children: [
              jsx(Switch, { checked: force, onCheckedChange: toggleForce, 'aria-label': 'Toggle force (block sending)' }),
              jsx('span', { className: 'font-medium', children: 'force' })
            ]
          }) }),
          enabled && res && jsxs(Fragment, { children: [
            jsx('div', {
              className: 'flex-1 min-w-0 flex items-center gap-2',
              children: [
                jsx('div', { className: 'w-28 h-1.5 rounded-full bg-(--ui-stroke-secondary) overflow-hidden',
                  children: jsx('div', { className: 'h-full rounded-full bg-(--ui-accent)', style: { width: Math.max(0, Math.min(100, res.score)) + '%' } }) }),
                jsxs('span', { className: 'font-semibold w-16 shrink-0 text-(--ui-text-secondary)', children: [
                  `${res.score} `,
                  jsx('span', { className: 'text-(--ui-text-quaternary) font-normal', children: `· ${res.tokens} tok` })
                ] })
              ]
            }),
            jsx('button', { type: 'button', className: btn, onClick: () => runAi('polish'),
              children: ai && ai.loading && ai.kind === 'polish' ? '✨ Polishing…' : '✨ AI polish' }),
            jsx(Tip, { tip: 'Start fine-tuning', children: jsx('button', { type: 'button', className: btn, onClick: () => { setFtOpen(!ftOpen); setAi(null) }, children: '🎯 Fine-tune' }) }),
            jsx(Tip, { tip: 'Turn off the current run', children: jsx('button', { type: 'button', className: btn, onClick: runOffline, children: ai && ai.loading && ai.kind === 'offline' ? '✍️ Editing…' : '✍️ Offline · 0 tokens' }) }),
            jsx(Tip, { tip: 'Generate output', style: { marginLeft: 'auto' }, children: jsx('button', { type: 'button', className: aiBtn, onClick: () => runAi('generate'), children: ai && ai.loading && ai.kind === 'generate' ? '🤖 Thinking…' : '🤖 AI generate' }) })
          ] }),
          enabled && !res && jsx('span', { className: 'flex-1 text-(--ui-text-tertiary)', children: 'Type above — BetterPrompt audits free, 0 tokens.' })
        ]
      }),
      // result panel for AI polish / generate
      (ai && (ai.loading || ai.improved)) && jsx('div', {
        className: 'mt-1 flex items-start gap-2 border border-(--ui-stroke-secondary) rounded-lg px-2 py-1.5',
        children: [
          jsx('div', { className: 'flex-1 min-w-0',
            children: jsx('div', {}, children_impl(ai)) }),
          !ai.loading && jsxs('div', { className: 'flex shrink-0 gap-1.5',
            children: [
              jsx('button', { type: 'button', className: aiBtn, onClick: () => apply(ai.improved), children: 'Apply' }),
              jsx('button', { type: 'button', className: btn, onClick: () => sendImproved(ai.improved), children: 'Send' })
            ] })
        ]
      }),
      ftOpen && jsx('div', {
        className: 'mt-1 border border-(--ui-stroke-secondary) rounded-lg px-2.5 py-2',
        children: [
          jsx('div', { className: 'mb-1.5 text-[0.72rem] font-semibold text-(--ui-accent)',
            children: '🎯 Fine-tune — answer a few project questions first' }),
          jsx('div', {
            className: 'grid grid-cols-2 gap-x-3 gap-y-1.5',
            children: QS.map(([k, label]) => jsx('label', {
              key: k, className: 'flex flex-col gap-0.5 text-(--ui-text-tertiary)',
              children: [
                jsx('span', { className: 'text-[0.68rem]', children: label }),
                jsx('input', {
                  type: 'text', value: answers[k] || '', placeholder: '(optional)',
                  onChange: (e) => setAns(k, e.target.value),
                  className: 'text-xs text-(--ui-text-secondary) border border-(--ui-stroke-secondary) rounded px-2 py-0.5 outline-none focus:border-(--ui-accent)'
                })
              ]
            }))
          }),
          jsxs('div', { className: 'mt-1.5 flex gap-2', children: [
            jsx('button', { type: 'button', className: aiBtn, onClick: buildFinetune,
              children: Object.keys(answers).filter(k => (answers[k] || '').trim()).length ? 'Build fine-tuned prompt' : 'Build with what I typed' }),
            jsx('button', { type: 'button', className: btn, onClick: () => setFtOpen(false), children: 'Cancel' })
          ] })
        ]
      }),
      (ai && !ai.loading && ai.improved) && jsx(Dialog, {
        open: popupOpen,
        onOpenChange: (o) => setPopupOpen(o),
        children: jsx(DialogContent, {
          className: 'max-h-[72vh] overflow-auto',
          children: [
            jsx(DialogHeader, {
              children: [
                jsx(DialogTitle, { children: kindLabel(ai) }),
                ai.kind !== 'polish' && jsx('div', { className: 'text-[0.68rem] font-medium text-(--ui-accent) -mt-1 mb-1', children: kindExplain(ai) }),
                jsx(DialogDescription, { className: 'whitespace-pre-wrap break-words', children: ai.improved })
              ]
            }),
            (ai.draft && ai.kind !== 'polish') && jsx('div', { className: 'mb-1 text-xs text-(--ui-text-quaternary)', children: 'Your draft: ' + ai.draft }),
            noteLine(ai) && jsxs('div', { className: 'mt-2 mb-1 text-xs text-(--ui-text-tertiary)', children: [ noteLine(ai) ] }),
            (ai.kind === 'offline' && ai.suggestions && ai.suggestions.length) && jsx('div', {
              className: 'mt-2 flex flex-col gap-1.5',
              children: ai.suggestions.map(s => jsx('div', {
                key: s.title, className: 'text-xs border border-(--ui-stroke-secondary) rounded px-2 py-1.5 flex items-start gap-2',
                children: [
                  jsx('div', { className: 'flex-1 min-w-0', children: [
                    jsx('span', { className: 'font-semibold text-(--ui-accent) mr-1', children: '💡 ' + s.title }),
                    jsx('span', { className: 'text-(--ui-text-secondary)', children: s.prompt })
                  ] }),
                  jsx('button', { type: 'button', className: 'shrink-0 px-2 py-0.5 rounded text-(--ui-accent) hover:opacity-80', onClick: () => apply(s.prompt), children: 'Use' })
                ]
              }))
            }),
            jsx(DialogFooter, {
              children: [
                jsx('button', { type: 'button', className: btn, onClick: () => setPopupOpen(false), children: 'Close' }),
                jsx('button', { type: 'button', className: 'px-3 py-1 rounded bg-(--ui-accent) text-(--ui-accent-fg) hover:opacity-80', onClick: () => apply(ai.improved), children: ai.kind === 'polish' || ai.kind === 'generate' ? 'Edit' : 'Apply' }),
                jsx('button', { type: 'button', className: btn, onClick: () => sendImproved(ai.improved), children: 'Send' })
              ]
            })
          ]
        })
      })
    ]
  })
}

function kindLabel(ai) {
  if (ai.kind === 'offline') return 'Preconfigured templates'
  if (ai.kind === 'polish') return '✨ AI polish'
  if (ai.kind === 'finetune') return '🎯 Fine-tuned prompt'
  return '🤖 Generated prompt'
}

// Hover tooltip — pure inline styles (Tailwind classes injected at runtime are not
// guaranteed to exist in the app's compiled CSS, so no class-based hover tricks).
function Tip({ tip, className, style, children }) {
  const [show, setShow] = useState(false)
  return jsx('span', {
    className: className || '',
    style: { position: 'relative', display: 'inline-flex', ...(style || {}) },
    title: tip,
    onMouseEnter: () => setShow(true),
    onMouseLeave: () => setShow(false),
    children: [
      children,
      show && jsx('span', {
        style: {
          position: 'absolute', bottom: '100%', left: '50%', transform: 'translateX(-50%)',
          marginBottom: '4px', whiteSpace: 'nowrap', zIndex: 60, pointerEvents: 'none',
          padding: '2px 8px', borderRadius: '4px', fontSize: '11px',
          color: 'var(--ui-text-primary)', background: 'var(--ui-stroke-secondary)'
        },
        children: tip
      })
    ]
  })
}

function kindExplain(ai) {
  if (ai.kind === 'polish') return 'This is your prompt tightened by the model — same ask, cleaned up. Apply puts it back in the box for editing; Send uses it as-is.'
  if (ai.kind === 'generate') return 'A new structured prompt built from your idea (goal, output + constraints). Model questions appear below when it needs answers.'
  if (ai.kind === 'finetune') return 'Built from your interview answers — everything you told it is now one prompt.'
  if (ai.kind === 'offline') return 'Edited locally — 0 tokens, no model. Every fix is listed in the notes below.'
  return ''
}

// Never let a suggestion replace the user's ask: if the model's output dropped
// every content word of the draft, reattach the original draft on top.
function guardImproved(draft, improved) {
  if (!draft || !improved) return { text: improved || draft, reattached: false }
  const skip = new Set(['about', 'that', 'with', 'from', 'your', 'this', 'have', 'just', 'like', 'and', 'the', 'then', 'make'])
  const words = (draft.toLowerCase().match(/[a-z]{4,}/g) || []).filter(w => !skip.has(w))
  const kept = words.length === 0 || words.some(w => improved.toLowerCase().includes(w))
  if (kept) return { text: improved, reattached: false }
  return { text: draft.trimEnd() + '\n\n' + improved.trim(), reattached: true }
}

function noteLine(ai) {
  const parts = []
  const ch = ai.changes
  if (ch) {
    if (ch.typos && ch.typos.length) parts.push('typos: ' + ch.typos.join(', '))
    if (ch.suspect && ch.suspect.length) parts.push('possible typos: ' + ch.suspect.join(', '))
    if (ch.filler && ch.filler.length) parts.push(ch.filler.length + ' filler removed')
    if (ch.runons) parts.push(ch.runons + ' run-on split')
    if (ch.grammar) parts.push(ch.grammar + ' grammar fix')
    if (ch.structure) parts.push('spec added')
    if (ai.scoreBefore != null && ai.scoreAfter != null) parts.push(`score ${ai.scoreBefore} → ${ai.scoreAfter}`)
  }
  if (ai.questions && ai.questions.length) parts.push('Clarify: ' + ai.questions.join(' · '))
  if (ai.error) parts.push(ai.error)
  return parts.join(' · ')
}

function children_impl(ai) {
  const parts = []
  if (ai.loading) parts.push(jsx('span', { key: 'l', className: 'text-(--ui-text-tertiary)', children:
    ai.kind === 'polish' ? 'Polishing on your model…'
      : ai.kind === 'finetune' ? 'Fine-tuning with your project context…'
      : 'Generating a better prompt…' }))
  else {
    if (ai.kind === 'finetune') parts.push(jsx('div', { key: 'ft', className: 'pb-1 text-[0.68rem] font-semibold text-(--ui-accent)', children: '🎯 Fine-tuned from your answers' }))
    if (ai.kind === 'offline') {
      const ch = ai.changes
      const notes = []
      if (ch) {
        if (ch.typos && ch.typos.length) notes.push('typos: ' + ch.typos.join(', '))
        if (ch.suspect && ch.suspect.length) notes.push('possible typos: ' + ch.suspect.join(', '))
        if (ch.filler && ch.filler.length) notes.push(ch.filler.length + ' filler removed')
        if (ch.runons) notes.push(ch.runons + ' run-on split')
        if (ch.grammar) notes.push(ch.grammar + ' grammar fix')
        if (ch.structure) notes.push('spec added')
      }
      const delta = (ai.scoreBefore != null && ai.scoreAfter != null) ? `score ${ai.scoreBefore} → ${ai.scoreAfter}` : ''
      parts.push(jsx('div', { key: 'off', className: 'pb-1 text-[0.68rem] font-semibold text-(--ui-accent)',
        children: '✍️ Offline edit · 0 tokens · no model' + (delta ? ' · ' + delta : '') }))
      if (notes.length) parts.push(jsx('div', { key: 'ch', className: 'pb-1 text-(--ui-text-quaternary)', children: 'Fixed: ' + notes.join(' · ') }))
    }
    if (ai.model) parts.push(jsx('div', { key: 'm', className: 'text-(--ui-text-quaternary) pb-1', children: `model: ${ai.model}` }))
    parts.push(jsx('div', { key: 't', className: 'text-(--ui-text-secondary) whitespace-pre-wrap', children: ai.improved }))
    if (ai.questions && ai.questions.length) parts.push(jsx('div', { key: 'q', className: 'mt-1 text-(--ui-accent)', children: 'Clarify: ' + ai.questions.join(' · ') }))
    if (ai.error) parts.push(jsx('div', { key: 'e', className: 'text-(--ui-text-tertiary) italic', children: ai.error }))
  }
  return parts
}

// ------------------------------------------------------------ statusbar chip
function ScoreChip({ storage }) {
  const sid = useValue(host.state.focusedSessionId)
  const busy = useValue(host.state.busy)
  const [res, setRes] = useState(null)
  const last = useRef('')

  useEffect(() => { last.current = ''; setRes(null) }, [sid])

  useEffect(() => {
    const loop = async () => {
      if (busy || !host.composer || !host.composer.getDraft) return
      try {
        const d = (await host.composer.getDraft(sid)) || ''
        if (d !== last.current) { last.current = d; setRes(d ? audit(d) : null) }
      } catch (e) {}
    }
    const id = setInterval(loop, 1600)
    loop()
    return () => clearInterval(id)
  }, [sid, busy])

  const on = !storage || storage.get('enabled') !== false
  if (!on || !res) return jsx('span', { className: 'px-1.5 text-[0.6875rem] text-(--ui-text-tertiary)', children: '⚡' })
  const c = res.score >= 75 ? 'text-(--ui-accent)' : `text-(--ui-text-secondary) opacity-${res.score < 55 ? '80' : '60'}`
  return jsx('button', {
    type: 'button', className: `px-1.5 text-[0.6875rem] ${res.score >= 75 ? 'text-(--ui-accent)' : 'text-(--ui-text-secondary)'}`,
    onClick: () => {
      haptic('tap')
      host.notify({ kind: 'info', message: `BetterPrompt ${res.score}/100 · ${res.tokens} tok · ${res.template}\n` +
        (res.issues.map(i => '• ' + i.msg).slice(0, 5).join('\n') || 'clean') })
    },
    children: `⚡ ${res.score}`
  })
}

// ---------------------------------------------------------------- plugin
export default {
  id: 'better-prompt',
  name: 'BetterPrompt',
  register(ctx) {
    ctx.register({ id: 'audit-bar', area: COMPOSER_AREAS.underside, render: () => jsx(AuditBar, { storage: ctx.storage, rest: (p, body) => ctx.rest(p, { method: 'POST', body }) }) })
    ctx.register({ id: 'score-chip', area: STATUSBAR_AREAS.right, order: 300, render: () => jsx(ScoreChip, { storage: ctx.storage }) })

    // Force mode + opt-in spelling / mistyped-command correction before sending.
    // While force is on, EVERY send is cancelled (the Send button is effectively
    // disabled) unless the submit came from the plugin's own popup (sendImproved
    // sets forceReleaseUntil just before submitting). Typo fixes still apply to
    // any send that is allowed.
    ctx.register({
      id: 'typo-middleware', area: COMPOSER_AREAS.middleware,
      data: {
        handler: (draft) => {
          const on = !ctx.storage || ctx.storage.get('enabled') !== false
          if (!draft || !draft.text) return draft
          if (bpEnabled && forceOn && Date.now() > forceReleaseUntil) {
            const now = Date.now()
            if (now - forceLastNotice > 4000) {
              forceLastNotice = now
              host.notify({ kind: 'info', message: 'Force on: sending is blocked — use ✍️ Offline, ✨ polish, ⟿ Generate or 🎯 Fine-tune, then Apply + Send.' })
            }
            return null
          }
          if (!on) return draft
          let t = draft.text
          for (const [w, f] of Object.entries(TYPO)) if (f) t = t.replace(new RegExp('\\b' + w + '\\b', 'ig'), f)
          // fix a leading slash command that was mistyped
          const m = t.match(/\/([a-z]+)\b/i)
          if (m && CMDS.includes(m[1].toLowerCase()) === false) {
            const cand = CMDS.find(c => c.length >= 4 && Math.abs(c.length - m[1].length) <= 1 && c[0] === m[1][0])
            if (cand) t = t.replace(m[0], '/' + cand)
          }
          return t === draft.text ? draft : { ...draft, text: t }
        }
      }
    })

    ctx.register({ id: 'audit-now', area: PALETTE_AREA, data: {
      id: 'bhp.audit', label: 'BetterPrompt: audit current prompt', run: async () => {
        const sid = host.state.focusedSessionId.get()
        const draft = (await host.composer.getDraft(sid)) || 'n/a'
        const r = audit(draft)
        host.notify({ kind: r.score >= 75 ? 'success' : 'info', message: `${r.score}/100 · ${r.tokens} tok · ${r.template}\n` +
          (r.issues.map(i => '• ' + i.msg).slice(0, 6).join('\n') || 'clean') })
      }
    } })

    ctx.register({ id: 'rewrite-now', area: PALETTE_AREA, data: {
      id: 'bhp.rewrite-local', label: 'BetterPrompt: rewrite current prompt (local, 0 tok)', run: async () => {
        const sid = host.state.focusedSessionId.get()
        const draft = (await host.composer.getDraft(sid)) || ''
        const r = audit(draft)
        if (r.rebuilded) { await host.composer.setDraft(sid, r.rebuilded); host.composer.focus(sid) }
      }
    } })

    ctx.register({ id: 'polish-now', area: PALETTE_AREA, data: {
      id: 'bhp.ai-polish', label: 'BetterPrompt: AI-polish current prompt in chat', run: async () => {
        const sid = host.state.focusedSessionId.get()
        haptic('tap')
        try { await host.composer.insertText(sid, '/bhp-rewrite ', { mode: 'prefix' }); host.composer.focus(sid) } catch (e) {}
      }
    } })
  }
}
