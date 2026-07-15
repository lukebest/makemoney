import { useState } from 'react'
import { errorMessage } from '../api'
import type { AIResult } from '../types'
import { Button } from './ui'

/** One-click AI coach block: trigger button, loading state, and result note. */
export function AICoach({ label, busyLabel, hint, disabled, run }: {
  label: string
  busyLabel: string
  hint?: string
  disabled?: boolean
  run: () => Promise<AIResult>
}) {
  const [result, setResult] = useState<AIResult>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function trigger() {
    setBusy(true)
    setError('')
    try { setResult(await run()) } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }

  return (
    <div className="ai-coach">
      <div className="ai-coach-head">
        <Button type="button" tone="ghost" onClick={() => void trigger()} disabled={busy || disabled}>
          {busy ? busyLabel : label}
        </Button>
        {hint && <small>{hint}</small>}
      </div>
      {error && <p className="form-message error" role="alert">{error}</p>}
      {result && (
        <blockquote className="ai-note">
          <p>{result.text}</p>
          <footer>{result.model}{result.generatedAt ? ` · ${new Date(result.generatedAt).toLocaleTimeString('zh-CN')}` : ''}</footer>
        </blockquote>
      )}
    </div>
  )
}
