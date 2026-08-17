import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { AICoach } from '../components/AICoach'
import { Button, PageHeader, Panel, StatusView } from '../components/ui'
import type { Trade, TradeInput, TradeSide } from '../types'

const nowLocal = () => {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

const initialTrade = (side: TradeSide): TradeInput => ({
  code: '', name: '', side, price: 0, quantity: 0, tradedAt: nowLocal(), reason: '', stopPrice: undefined,
  questions: side === 'buy' ? ['', '', ''] : undefined,
})

const nativeMoney = (value: number, currency: 'CNY' | 'HKD' = 'CNY') =>
  new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value || 0)

export function Trades() {
  const [params] = useSearchParams()
  const [side, setSide] = useState<TradeSide>('buy')
  const [form, setForm] = useState<TradeInput>(() => initialTrade('buy'))
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [trendWarning, setTrendWarning] = useState('')
  const [listWarning, setListWarning] = useState('')
  const [trendChecking, setTrendChecking] = useState(false)
  const [trendCheckedCode, setTrendCheckedCode] = useState('')
  const isHongKong = /^(?:HK)?\d{5}$/i.test(form.code.trim())
  const normalizedCode = form.code.trim().toUpperCase().replace(/^(SH|SZ|HK)/, '')
  const trendGateReady = /^(?:\d{5}|\d{6})$/.test(normalizedCode)
    && trendCheckedCode === normalizedCode

  const load = useCallback(async () => {
    setLoading(true)
    try { setTrades(await api.trades()) } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const code = (params.get('code') || '').replace(/\D/g, '')
    if (code.length < 5) return
    const price = Number(params.get('price') || 0)
    const stop = Number(params.get('stop') || 0)
    setSide('buy')
    setForm((current) => ({
      ...current,
      side: 'buy',
      code,
      name: params.get('name') || current.name,
      price: price > 0 ? price : current.price,
      stopPrice: stop > 0 ? stop : current.stopPrice,
      questions: current.questions || ['', '', ''],
    }))
  }, [params])
  useEffect(() => {
    if (side !== 'buy') return
    const normalized = form.code.trim().toUpperCase().replace(/^(SH|SZ|HK)/, '')
    if (!/^(?:\d{5}|\d{6})$/.test(normalized)) {
      setTrendWarning('')
      setListWarning('')
      setTrendCheckedCode('')
      return
    }
    setTrendWarning('')
    setTrendCheckedCode('')
    let cancelled = false
    const timer = window.setTimeout(async () => {
      setTrendChecking(true)
      try {
        const analysis = await api.stock(normalized)
        if (cancelled) return
        const warnings = []
        if (analysis.trend !== '多头排列') {
          warnings.push(`当前趋势为“${analysis.trend}”，不符合只做主升浪`)
        }
        if (analysis.structure?.phase === 'distribution') {
          warnings.push('量价规则判定为疑似出货阶段')
        }
        setTrendWarning(warnings.join('；'))
        setTrendCheckedCode(normalized)
      } catch {
        if (!cancelled) {
          setTrendWarning('趋势校验失败，无法确认是否处于主升浪')
          setTrendCheckedCode(normalized)
        }
      } finally {
        if (!cancelled) setTrendChecking(false)
      }
    }, 600)
    void api.today().then((brief) => {
      if (cancelled) return
      const codes = brief.discipline?.planCodes ?? []
      setListWarning(
        brief.discipline?.hasPlan && codes.length && !codes.includes(normalized)
          ? '该股不在今日精选清单，记录后将记为纪律违例'
          : '',
      )
    }).catch(() => undefined)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [form.code, side])

  function switchSide(next: TradeSide) {
    setSide(next)
    setForm(initialTrade(next))
    setError('')
    setListWarning('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const gates = [trendWarning, listWarning].filter(Boolean)
    if (
      side === 'buy'
      && gates.length
      && !window.confirm(`纪律闸门：${gates.join('；')}\n\n该页面记录真实交易。确认仍要记录这笔买入吗？`)
    ) return
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const recorded = await api.createTrade(form)
      setSuccess(
        recorded.violated
          ? '买入已入账，但已记为清单外违例'
          : `${side === 'buy' ? '买入' : '卖出'}记录已入账`,
      )
      setForm(initialTrade(side))
      await load()
    } catch (e) { setError(errorMessage(e)) } finally { setSaving(false) }
  }

  const setQuestion = (index: number, value: string) => {
    const questions = [...(form.questions || ['', '', ''])] as [string, string, string]
    questions[index] = value
    setForm({ ...form, questions })
  }

  return (
    <div className="page">
      <PageHeader eyebrow="EXECUTION JOURNAL · 交易执行" title="每次扣动扳机，都要留痕" description="买入前回答三个问题，卖出后留下真实原因。记录不是装饰，是下一次清醒的依据。" />
      <div className="trade-layout">
        <Panel className="trade-ticket">
          <div className="trade-tabs" role="tablist" aria-label="交易方向">
            <button role="tab" aria-selected={side === 'buy'} className={side === 'buy' ? 'active buy-tab' : ''} onClick={() => switchSide('buy')}>买入委托</button>
            <button role="tab" aria-selected={side === 'sell'} className={side === 'sell' ? 'active sell-tab' : ''} onClick={() => switchSide('sell')}>卖出记录</button>
          </div>
          <form className="trade-form" onSubmit={submit}>
            <div className="form-grid">
              <label>股票代码<input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="A股 000001 / 港股通 00700" /></label>
              <label>股票名称<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="可选" /></label>
              <label>成交价格<input required type="number" min="0.01" step="0.01" value={form.price || ''} onChange={(e) => setForm({ ...form, price: Number(e.target.value) })} /></label>
              <label>成交数量<input required type="number" min={side === 'buy' && !isHongKong ? 100 : 1} step={side === 'buy' && !isHongKong ? 100 : 1} value={form.quantity || ''} onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })} /><small>{isHongKong ? '港股每手股数因股票而异，请按实际数量填写' : 'A股买入数量须为100股的整数倍'}</small></label>
              <label className="full">成交时间<input required type="datetime-local" value={form.tradedAt} onChange={(e) => setForm({ ...form, tradedAt: e.target.value })} /></label>
            </div>

            {side === 'buy' ? <fieldset className="three-questions">
              <legend><span>BUY GATE</span> 买入前必答</legend>
              <label><i>壹</i><span>为什么涨？<small>上涨逻辑是否清晰、可验证</small></span><textarea required rows={2} value={form.questions?.[0] || ''} onChange={(e) => setQuestion(0, e.target.value)} /></label>
              <label><i>贰</i><span>谁在买？<small>成交量与资金承接是否真实</small></span><textarea required rows={2} value={form.questions?.[1] || ''} onChange={(e) => setQuestion(1, e.target.value)} /></label>
              <label><i>叁</i><span>还能涨吗？<small>上方空间与盈亏比是否合理</small></span><textarea required rows={2} value={form.questions?.[2] || ''} onChange={(e) => setQuestion(2, e.target.value)} /></label>
              <label className="stop-input"><span>预设止损价</span><input required type="number" min="0.01" step="0.01" value={form.stopPrice || ''} onChange={(e) => setForm({ ...form, stopPrice: Number(e.target.value) })} /></label>
              {trendChecking && <p className="trend-gate checking">正在校验是否处于主升浪…</p>}
              {trendWarning && <p className="trend-gate warning" role="alert">纪律闸门：{trendWarning}。提交时必须二次确认。</p>}
              {listWarning && <p className="trend-gate warning" role="alert">纪律闸门：{listWarning}。提交时必须二次确认。</p>}
              {!trendChecking && trendCheckedCode && !trendWarning && <p className="trend-gate passed">趋势闸门通过：当前未发现非上升趋势或疑似出货警告。</p>}
              <AICoach
                label="AI 审查三问回答"
                busyLabel="纪律教练审查中…"
                hint="Grok 对照该股实时信号审查你的买入理由"
                disabled={!form.code.trim() || !(form.questions?.[0] || '').trim()}
                run={() => api.aiReviewTrade({
                  code: form.code.trim().toUpperCase().replace(/^(SH|SZ|HK)/, ''),
                  price: form.price,
                  quantity: form.quantity,
                  stopLoss: form.stopPrice,
                  logic: form.questions?.[0] || '',
                  fundsAnswer: form.questions?.[1] || '',
                  spaceAnswer: form.questions?.[2] || '',
                })}
              />
            </fieldset> : <label className="sell-reason">卖出原因<textarea required rows={5} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="止盈、止损、逻辑失效或仓位调整。请诚实记录…" /></label>}

            {error && <p className="form-message error" role="alert">{error}</p>}
            {success && <p className="form-message success" role="status">{success}</p>}
            <Button type="submit" className="submit-trade" disabled={saving || (side === 'buy' && !trendGateReady)}>{saving ? '正在入账…' : `确认记录${side === 'buy' ? '买入' : '卖出'}`}</Button>
          </form>
        </Panel>

        <aside className="discipline-rail">
          <span>今日交易戒律</span>
          <blockquote>“计划你的交易，<br />交易你的计划。”</blockquote>
          <ol><li>不追高</li><li>不补亏</li><li>不侥幸</li></ol>
        </aside>
      </div>

      <Panel title="交易流水" eyebrow="EXECUTION HISTORY">
        {loading ? <StatusView state="loading" /> : !trades.length ? <StatusView state="empty" message="尚无交易记录" /> : <div className="trade-history">
          {[...trades].sort((a, b) => new Date(b.tradedAt).getTime() - new Date(a.tradedAt).getTime()).map((trade) => (
            <article key={trade.id} className={trade.violated ? 'warning-row' : undefined}>
              <time>{new Date(trade.tradedAt).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}<small>{new Date(trade.tradedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</small></time>
              <span className={`side-badge ${trade.side}`}>{trade.side === 'buy' ? '买' : '卖'}</span>
              <div className="trade-symbol"><b>{trade.name || trade.code}</b><small>{trade.code}{trade.market === 'HK' ? ' · 港股' : ''}{trade.violated ? ' · 违例' : ''}</small></div>
              <div><span>{trade.quantity.toLocaleString()} 股 × {trade.price.toFixed(2)}</span><strong>{nativeMoney(trade.quantity * trade.price, trade.currency)}</strong></div>
              <p>{trade.reason || trade.questions?.[0] || '—'}</p>
            </article>
          ))}
        </div>}
      </Panel>
    </div>
  )
}
