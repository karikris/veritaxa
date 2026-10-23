// Compose Smart Signals into a per-action policy. Returns a decision: 'allow' | 'step_up' | 'block'.
// Run this on the *verified* event from getEvent(eventId) — never on client-reported values.

function evaluateSignals(event, { risk = 'high' } = {}) {
  const reasons = []
  // Absent when no bot was detected; when present, name/provider/category/identity/confidence are
  // all set. The three-valued `event.bot` is a verdict, not a description — it can't separate
  // Googlebot from an AI agent from Playwright, and each of those wants a different answer.
  const bot = event.bot_info

  // Claims a public identity (Googlebot, GPTBot) and fails verification. Nothing legitimate does
  // this, so it outranks every other signal and every action's risk level.
  if (bot?.identity === 'spoofed') return { decision: 'block', reasons: [`spoofed_bot:${bot.name}`] }

  // Hard blocks — reject regardless of action risk.
  if (event.bot === 'bad') reasons.push(`bot:${bot?.category ?? 'automation'}`)
  // A declared crawler is not fraud. Blocking a verified one on a crawlable route is an SEO
  // outage, so only the high-risk actions — where no crawler belongs — fail closed on it.
  if (event.bot === 'good' && risk === 'high') reasons.push(`crawler:${bot?.name ?? 'unknown'}`)
  if (event.tampering) reasons.push('tampering')
  if (reasons.length) return { decision: 'block', reasons }

  // Anonymizing network / known-bad IP — block for high-risk, step-up otherwise.
  const networkFlags = []
  if (event.vpn) networkFlags.push('vpn')
  if (event.proxy) networkFlags.push('proxy')
  // ip_blocklist is an object of flags, always present — check the sub-fields, not truthiness.
  const ipbl = event.ip_blocklist
  if (ipbl && (ipbl.attack_source || ipbl.email_spam || ipbl.tor_node)) networkFlags.push('ip_blocklist')
  if (networkFlags.length) {
    return risk === 'high'
      ? { decision: 'block', reasons: networkFlags }
      : { decision: 'step_up', reasons: networkFlags }
  }

  // Soft signals — score but don't block on their own.
  const soft = []
  if (event.incognito) soft.push('incognito')
  if (event.location_spoofing) soft.push('location_spoofing')
  if (event.virtual_machine) soft.push('virtual_machine')
  if ((event.suspect_score ?? 0) > 0) soft.push(`suspect_score=${event.suspect_score}`)
  if (soft.length && risk === 'high') return { decision: 'step_up', reasons: soft }

  return { decision: 'allow', reasons: soft }
}

module.exports = { evaluateSignals }
