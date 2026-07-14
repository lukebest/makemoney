import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage } from '../api'
import { Button, PageHeader, Panel, StatusView, money } from '../components/ui'
import type { Trade, TradeInput, TradeSide } from '../types'

const nowLocal = () => {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

const initialTrade = (side: TradeSide): TradeInput => ({
  code: '', name: '', side, price: 0, quantity: 0, tradedAt: nowLocal(), reason: '', stopPrice: undefined,
  questions: side === 'buy' ? ['', '', ''] : undefined,
})

export function Trades() {
  const [side, setSide] = useState<TradeSide>('buy')
  const [form, setForm] = useState<TradeInput>(() => initialTrade('buy'))
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try { setTrades(await api.trades()) } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  function switchSide(next: TradeSide) {
    setSide(next)
    setForm(initialTrade(next))
    setError('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      await api.createTrade(form)
      setSuccess(`${side === 'buy' ? '买入' : '卖出'}记录已入账`)
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
              <label>股票代码<input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="000001" /></label>
              <label>股票名称<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="可选" /></label>
              <label>成交价格<input required type="number" min="0.01" step="0.01" value={form.price || ''} onChange={(e) => setForm({ ...form, price: Number(e.target.value) })} /></label>
              <label>成交数量<input required type="number" min={side === 'buy' ? 100 : 1} step={side === 'buy' ? 100 : 1} value={form.quantity || ''} onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })} /></label>
              <label className="full">成交时间<input required type="datetime-local" value={form.tradedAt} onChange={(e) => setForm({ ...form, tradedAt: e.target.value })} /></label>
            </div>

            {side === 'buy' ? <fieldset className="three-questions">
              <legend><span>BUY GATE</span> 买入前必答</legend>
              <label><i>壹</i><span>为什么涨？<small>上涨逻辑是否清晰、可验证</small></span><textarea required rows={2} value={form.questions?.[0] || ''} onChange={(e) => setQuestion(0, e.target.value)} /></label>
              <label><i>贰</i><span>谁在买？<small>成交量与资金承接是否真实</small></span><textarea required rows={2} value={form.questions?.[1] || ''} onChange={(e) => setQuestion(1, e.target.value)} /></label>
              <label><i>叁</i><span>还能涨吗？<small>上方空间与盈亏比是否合理</small></span><textarea required rows={2} value={form.questions?.[2] || ''} onChange={(e) => setQuestion(2, e.target.value)} /></label>
              <label className="stop-input"><span>预设止损价</span><input required type="number" min="0.01" step="0.01" value={form.stopPrice || ''} onChange={(e) => setForm({ ...form, stopPrice: Number(e.target.value) })} /></label>
            </fieldset> : <label className="sell-reason">卖出原因<textarea required rows={5} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="止盈、止损、逻辑失效或仓位调整。请诚实记录…" /></label>}

            {error && <p className="form-message error" role="alert">{error}</p>}
            {success && <p className="form-message success" role="status">{success}</p>}
            <Button type="submit" className="submit-trade" disabled={saving}>{saving ? '正在入账…' : `确认记录${side === 'buy' ? '买入' : '卖出'}`}</Button>
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
            <article key={trade.id}>
              <time>{new Date(trade.tradedAt).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}<small>{new Date(trade.tradedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</small></time>
              <span className={`side-badge ${trade.side}`}>{trade.side === 'buy' ? '买' : '卖'}</span>
              <div className="trade-symbol"><b>{trade.name || trade.code}</b><small>{trade.code}</small></div>
              <div><span>{trade.quantity.toLocaleString()} 股 × {trade.price.toFixed(2)}</span><strong>{money(trade.quantity * trade.price)}</strong></div>
              <p>{trade.reason || trade.questions?.[0] || '—'}</p>
            </article>
          ))}
        </div>}
      </Panel>
    </div>
  )
}
