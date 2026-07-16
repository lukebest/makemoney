import { useCallback, useEffect, useState } from 'react'
import { View, Text, Input, Button, Textarea, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'

import Panel from '../../components/Panel'
import StatusView from '../../components/StatusView'
import { api, errorMessage } from '../../shared/api'
import { money } from '../../shared/format'
import type { Trade, TradeInput, TradeSide } from '../../shared/types'

import './index.scss'

const nowLocal = () => {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

const initialTrade = (side: TradeSide): TradeInput => ({
  code: '', name: '', side, price: 0, quantity: 0, tradedAt: nowLocal(), reason: '',
  stopPrice: undefined, questions: side === 'buy' ? ['', '', ''] : undefined,
})

const CODE_RE = /^(?:\d{5}|\d{6})$/

export default function Trades() {
  const [side, setSide] = useState<TradeSide>('buy')
  const [form, setForm] = useState<TradeInput>(() => initialTrade('buy'))
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [trendWarning, setTrendWarning] = useState('')
  const [trendChecking, setTrendChecking] = useState(false)

  const normalizedCode = form.code.trim().toUpperCase().replace(/^(SH|SZ|HK)/, '')
  const isHongKong = /^(?:HK)?\d{5}$/i.test(form.code.trim())

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTrades(await api.trades())
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (side !== 'buy' || !CODE_RE.test(normalizedCode)) {
      setTrendWarning('')
      return undefined
    }
    let cancelled = false
    setTrendWarning('')
    const timer = setTimeout(async () => {
      setTrendChecking(true)
      try {
        const analysis = await api.stock(normalizedCode)
        if (cancelled) return
        const warnings: string[] = []
        if (analysis.trend !== '多头排列') warnings.push(`当前趋势为“${analysis.trend}”，不符合只做主升浪`)
        if (analysis.structure?.phase === 'distribution') warnings.push('量价规则判定为疑似出货阶段')
        setTrendWarning(warnings.join('；'))
      } catch {
        if (!cancelled) setTrendWarning('趋势校验失败，无法确认是否处于主升浪')
      } finally {
        if (!cancelled) setTrendChecking(false)
      }
    }, 600)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [normalizedCode, side])

  function switchSide(next: TradeSide) {
    setSide(next)
    setForm(initialTrade(next))
    setError('')
    setSuccess('')
  }

  const setQuestion = (index: number, value: string) => {
    const questions = [...(form.questions || ['', '', ''])] as [string, string, string]
    questions[index] = value
    setForm({ ...form, questions })
  }

  async function submit() {
    if (!form.code.trim() || !(form.price > 0) || !(form.quantity > 0)) {
      setError('请填写代码、价格与数量')
      return
    }
    if (side === 'buy') {
      const q = form.questions || ['', '', '']
      if (!q[0].trim() || !q[1].trim() || !q[2].trim() || !(form.stopPrice && form.stopPrice > 0)) {
        setError('买入前请回答三个问题并设置止损价')
        return
      }
      if (trendWarning) {
        const res = await Taro.showModal({
          title: '纪律闸门',
          content: `${trendWarning}。\n\n该页面记录真实交易，确认仍要记录这笔买入吗？`,
        })
        if (!res.confirm) return
      }
    } else if (!form.reason?.trim()) {
      setError('请填写卖出原因')
      return
    }

    setSaving(true)
    setError('')
    setSuccess('')
    try {
      await api.createTrade(form)
      setSuccess(`${side === 'buy' ? '买入' : '卖出'}记录已入账`)
      setForm(initialTrade(side))
      await load()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <ScrollView scrollY className='page trades'>
      <View className='page-header'>
        <Text className='page-header__eyebrow'>EXECUTION JOURNAL · 交易执行</Text>
        <Text className='page-header__title'>每次扣动扳机，都要留痕</Text>
        <Text className='page-header__desc'>买入前回答三个问题，卖出后留下真实原因。</Text>
      </View>

      <Panel>
        <View className='trade-tabs'>
          <Text className={`trade-tabs__tab ${side === 'buy' ? 'trade-tabs__tab--active-buy' : ''}`} onClick={() => switchSide('buy')}>买入委托</Text>
          <Text className={`trade-tabs__tab ${side === 'sell' ? 'trade-tabs__tab--active-sell' : ''}`} onClick={() => switchSide('sell')}>卖出记录</Text>
        </View>

        <View className='field'>
          <Text className='field__label'>股票代码</Text>
          <Input className='field__input' value={form.code} placeholder='A股 000001 / 港股 00700' onInput={(e) => setForm({ ...form, code: e.detail.value })} />
        </View>
        <View className='field'>
          <Text className='field__label'>股票名称</Text>
          <Input className='field__input' value={form.name} placeholder='可选' onInput={(e) => setForm({ ...form, name: e.detail.value })} />
        </View>
        <View className='field'>
          <Text className='field__label'>成交价格</Text>
          <Input className='field__input' type='digit' value={form.price ? String(form.price) : ''} onInput={(e) => setForm({ ...form, price: Number(e.detail.value) })} />
        </View>
        <View className='field'>
          <Text className='field__label'>成交数量</Text>
          <Input className='field__input' type='number' value={form.quantity ? String(form.quantity) : ''} onInput={(e) => setForm({ ...form, quantity: Number(e.detail.value) })} />
          <Text className='field__hint'>{isHongKong ? '港股按实际手数填写' : 'A股买入数量须为100股的整数倍'}</Text>
        </View>

        {side === 'buy' ? (
          <View className='three-questions'>
            <Text className='three-questions__legend'>买入前必答</Text>
            <View className='field'>
              <Text className='field__label'>壹 · 为什么涨？（上涨逻辑是否清晰）</Text>
              <Textarea className='field__textarea' value={form.questions?.[0] || ''} onInput={(e) => setQuestion(0, e.detail.value)} />
            </View>
            <View className='field'>
              <Text className='field__label'>贰 · 谁在买？（成交量与资金承接）</Text>
              <Textarea className='field__textarea' value={form.questions?.[1] || ''} onInput={(e) => setQuestion(1, e.detail.value)} />
            </View>
            <View className='field'>
              <Text className='field__label'>叁 · 还能涨吗？（上方空间与盈亏比）</Text>
              <Textarea className='field__textarea' value={form.questions?.[2] || ''} onInput={(e) => setQuestion(2, e.detail.value)} />
            </View>
            <View className='field'>
              <Text className='field__label'>预设止损价</Text>
              <Input className='field__input' type='digit' value={form.stopPrice ? String(form.stopPrice) : ''} onInput={(e) => setForm({ ...form, stopPrice: Number(e.detail.value) })} />
            </View>
            {trendChecking && <Text className='trend-gate trend-gate--checking'>正在校验是否处于主升浪…</Text>}
            {!trendChecking && trendWarning && <Text className='trend-gate trend-gate--warning'>纪律闸门：{trendWarning}。提交时需二次确认。</Text>}
            {!trendChecking && !trendWarning && CODE_RE.test(normalizedCode) && (
              <Text className='trend-gate trend-gate--passed'>趋势闸门通过：未发现非上升趋势或疑似出货警告。</Text>
            )}
          </View>
        ) : (
          <View className='field'>
            <Text className='field__label'>卖出原因</Text>
            <Textarea className='field__textarea' value={form.reason} placeholder='止盈、止损、逻辑失效或仓位调整。请诚实记录…' onInput={(e) => setForm({ ...form, reason: e.detail.value })} />
          </View>
        )}

        {error ? <Text className='loss form-msg'>{error}</Text> : null}
        {success ? <Text className='brass form-msg'>{success}</Text> : null}

        <Button className='pill-btn submit-trade' loading={saving} onClick={() => void submit()}>
          {saving ? '正在入账…' : `确认记录${side === 'buy' ? '买入' : '卖出'}`}
        </Button>
      </Panel>

      <Panel title='交易流水' eyebrow='EXECUTION HISTORY'>
        {loading ? (
          <StatusView state='loading' />
        ) : !trades.length ? (
          <StatusView state='empty' message='尚无交易记录' />
        ) : (
          [...trades]
            .sort((a, b) => new Date(b.tradedAt).getTime() - new Date(a.tradedAt).getTime())
            .map((trade) => (
              <View key={trade.id} className='trade-item'>
                <Text className={`trade-item__side trade-item__side--${trade.side}`}>{trade.side === 'buy' ? '买' : '卖'}</Text>
                <View className='trade-item__body'>
                  <Text className='trade-item__symbol'>{trade.name || trade.code}</Text>
                  <Text className='trade-item__detail'>
                    {trade.quantity.toLocaleString()} 股 × {trade.price.toFixed(2)} · {money(trade.quantity * trade.price)}
                  </Text>
                  <Text className='trade-item__reason'>{trade.reason || trade.questions?.[0] || '—'}</Text>
                </View>
                <Text className='trade-item__time'>{trade.tradedAt.slice(5, 10)}</Text>
              </View>
            ))
        )}
      </Panel>
    </ScrollView>
  )
}
