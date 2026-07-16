import { useCallback, useEffect, useState } from 'react'
import { View, Text, Input, Button, Picker, Textarea, ScrollView } from '@tarojs/components'
import Taro, { usePullDownRefresh, stopPullDownRefresh } from '@tarojs/taro'

import Panel from '../../components/Panel'
import Metric from '../../components/Metric'
import StatusView from '../../components/StatusView'
import { api, errorMessage } from '../../shared/api'
import { money, percent } from '../../shared/format'
import type { PortfolioSummary, Position, PositionInput, Settings } from '../../shared/types'

import './index.scss'

const emptyForm: PositionInput = {
  code: '', name: '', quantity: 0, costPrice: 0, stopPrice: 0, tier: 1, note: '',
}
const tierOptions = ['底仓 · 目标30%', '机动仓 · 目标30%']

export default function Positions() {
  const [positions, setPositions] = useState<Position[]>([])
  const [settings, setSettings] = useState<Settings>({ totalCapital: 0 })
  const [portfolio, setPortfolio] = useState<PortfolioSummary>({
    totalCapital: 0, investedCost: 0, realizedPnl: 0, availableFunds: 0,
  })
  const [capitalInput, setCapitalInput] = useState('')
  const [form, setForm] = useState<PositionInput>(emptyForm)
  const [editingId, setEditingId] = useState<Position['id']>()
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [positionData, settingData] = await Promise.all([api.positionStatus(), api.settings()])
      setPositions(positionData.items)
      setPortfolio(positionData.summary)
      setSettings(settingData)
      setCapitalInput(String(settingData.totalCapital || ''))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  usePullDownRefresh(() => {
    void load().finally(() => stopPullDownRefresh())
  })

  const marketValue = positions.reduce(
    (sum, p) => sum + (p.marketValue ?? p.quantity * (p.currentPrice || p.costPrice) * (p.fxRate || 1)),
    0,
  )
  const cost = positions.reduce(
    (sum, p) => sum + (p.costValue ?? p.quantity * p.costPrice * (p.fxRate || 1)),
    0,
  )
  const pnl = marketValue - cost
  const stopAlerts = positions.filter((p) => p.stopPrice > 0 && p.currentPrice <= p.stopPrice)

  const editingPosition = positions.find((p) => p.id === editingId)
  const editingCost = editingPosition
    ? editingPosition.costValue ?? editingPosition.quantity * editingPosition.costPrice * (editingPosition.fxRate || 1)
    : 0
  const singleLimit = settings.totalCapital * (settings.maxPositionRatio ?? 0.3)
  const investedLimit = settings.totalCapital * (settings.maxInvestedRatio ?? 0.6)
  const estimatedCost = form.quantity * form.costPrice
  const spendableFunds = portfolio.availableFunds + editingCost

  async function saveCapital() {
    const value = Number(capitalInput)
    if (!(value > 0)) {
      setError('请输入有效的账户总资金')
      return
    }
    try {
      await api.updateSettings({ ...settings, totalCapital: value })
      await load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  function beginEdit(position?: Position) {
    setFormError('')
    if (position) {
      setEditingId(position.id)
      setForm({
        code: position.code, name: position.name, quantity: position.quantity,
        costPrice: position.costPrice, stopPrice: position.stopPrice, tier: position.tier,
        note: position.note || '',
      })
    } else {
      setEditingId(undefined)
      setForm(emptyForm)
    }
    setOpen(true)
  }

  async function savePosition() {
    if (!form.code.trim() || !(form.quantity > 0) || !(form.costPrice > 0) || !(form.stopPrice > 0)) {
      setFormError('请完整填写代码、数量、成本价与止损价')
      return
    }
    if (form.stopPrice >= form.costPrice) {
      setFormError('止损价必须低于成本价')
      return
    }
    setSaving(true)
    setFormError('')
    try {
      if (editingId != null) await api.updatePosition(editingId, form)
      else await api.createPosition(form)
      setOpen(false)
      await load()
    } catch (e) {
      setFormError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  async function remove(position: Position) {
    const res = await Taro.showModal({
      title: '删除持仓',
      content: `确认删除 ${position.name || position.code} 的持仓？`,
    })
    if (!res.confirm) return
    try {
      await api.deletePosition(position.id)
      await load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <ScrollView scrollY className='page positions'>
      <View className='page-header'>
        <Text className='page-header__eyebrow'>POSITION CONTROL · 仓位管理</Text>
        <Text className='page-header__title'>仓位，是生存的刻度</Text>
        <Text className='page-header__desc'>用 3 · 3 · 4 结构限制冲动。先决定最多亏多少，再决定可以买多少。</Text>
      </View>

      {error ? <Text className='inline-error' onClick={() => setError('')}>{error}（点击关闭）</Text> : null}

      {loading ? (
        <StatusView state='loading' />
      ) : (
        <View>
          <Panel title='账户资金' eyebrow='CAPITAL'>
            <View className='capital-form'>
              <Input
                className='capital-form__input'
                type='number'
                value={capitalInput}
                placeholder='账户总资金'
                onInput={(e) => setCapitalInput(e.detail.value)}
              />
              <Button className='pill-btn pill-btn--ghost' size='mini' onClick={() => void saveCapital()}>保存</Button>
            </View>
            <View className='metric-row capital-metrics'>
              <Metric label='持仓市值' value={money(marketValue)} />
              <Metric label='浮动盈亏' value={money(pnl)} tone={pnl >= 0 ? 'gain' : 'loss'} note={cost ? percent((pnl / cost) * 100) : '0.00%'} />
              <Metric label='可用资金' value={money(Math.max(0, portfolio.availableFunds))} />
            </View>
          </Panel>

          {stopAlerts.length > 0 && (
            <View className='source-notice'>
              <Text className='source-notice__title'>止损线触发 · {stopAlerts.length} 只</Text>
              <Text className='source-notice__text'>
                {stopAlerts.map((i) => i.name || i.code).join('、')} 已触及预设退出价，请按纪律处置。
              </Text>
            </View>
          )}

          <Panel
            title={`当前持仓 · ${positions.length}`}
            eyebrow='OPEN POSITIONS'
            action={<Button className='pill-btn' size='mini' onClick={() => beginEdit()}>＋ 新增</Button>}
          >
            {!positions.length ? (
              <StatusView state='empty' message='新增第一笔持仓，开始记录风险' />
            ) : (
              positions.map((p) => {
                const itemPnl = p.unrealizedPnl ?? (p.currentPrice - p.costPrice) * p.quantity * (p.fxRate || 1)
                const warning = p.stopPrice > 0 && p.currentPrice <= p.stopPrice
                return (
                  <View key={p.id} className={`pos-row ${warning ? 'pos-row--warning' : ''}`}>
                    <View className='pos-row__id'>
                      <Text className='pos-row__name'>{p.name || '未命名'}</Text>
                      <Text className='pos-row__code'>
                        {p.code}{p.market === 'HK' ? ' · 港股' : ''} · {p.tier === 1 ? '底仓' : '机动'}
                      </Text>
                    </View>
                    <View className='pos-row__nums'>
                      <Text className='pos-row__value'>{money(p.marketValue ?? p.quantity * p.currentPrice * (p.fxRate || 1))}</Text>
                      <Text className={itemPnl >= 0 ? 'gain' : 'loss'}>{money(itemPnl)}</Text>
                      <Text className='muted'>
                        {p.costPrice.toFixed(2)} / {p.currentPrice.toFixed(2)} · 止损 {p.stopPrice.toFixed(2)}
                      </Text>
                    </View>
                    <View className='pos-row__actions'>
                      <Button className='pill-btn pill-btn--ghost' size='mini' onClick={() => beginEdit(p)}>编辑</Button>
                      <Button className='pill-btn pill-btn--danger' size='mini' onClick={() => void remove(p)}>删除</Button>
                    </View>
                  </View>
                )
              })
            )}
          </Panel>
        </View>
      )}

      {open && (
        <View className='modal'>
          <View className='modal__backdrop' onClick={() => setOpen(false)} />
          <View className='modal__sheet'>
            <View className='modal__head'>
              <Text className='modal__title'>{editingId != null ? '编辑持仓' : '新增持仓'}</Text>
              <Text className='modal__close' onClick={() => setOpen(false)}>×</Text>
            </View>

            <View className='field'>
              <Text className='field__label'>股票代码</Text>
              <Input
                className='field__input'
                value={form.code}
                disabled={editingId != null}
                placeholder='A股 600519 / 港股 00700'
                onInput={(e) => setForm({ ...form, code: e.detail.value })}
              />
            </View>
            <View className='field'>
              <Text className='field__label'>股票名称</Text>
              <Input className='field__input' value={form.name} placeholder='贵州茅台' onInput={(e) => setForm({ ...form, name: e.detail.value })} />
            </View>
            <View className='field'>
              <Text className='field__label'>持有数量</Text>
              <Input className='field__input' type='number' value={form.quantity ? String(form.quantity) : ''} onInput={(e) => setForm({ ...form, quantity: Number(e.detail.value) })} />
            </View>
            <View className='field'>
              <Text className='field__label'>持仓层级</Text>
              <Picker mode='selector' range={tierOptions} value={form.tier - 1} onChange={(e) => setForm({ ...form, tier: (Number(e.detail.value) + 1) as 1 | 2 })}>
                <View className='field__input'>{tierOptions[form.tier - 1]}</View>
              </Picker>
            </View>
            <View className='field'>
              <Text className='field__label'>成本价</Text>
              <Input
                className='field__input'
                type='digit'
                value={form.costPrice ? String(form.costPrice) : ''}
                onInput={(e) => {
                  const costPrice = Number(e.detail.value)
                  setForm((prev) => ({
                    ...prev,
                    costPrice,
                    stopPrice: prev.stopPrice || Number((costPrice * 0.95).toFixed(2)),
                  }))
                }}
              />
            </View>
            <View className='field'>
              <Text className='field__label'>止损价</Text>
              <Input className='field__input' type='digit' value={form.stopPrice ? String(form.stopPrice) : ''} onInput={(e) => setForm({ ...form, stopPrice: Number(e.detail.value) })} />
              <Text className='field__hint'>默认成本价下方 5%，可按策略调整</Text>
            </View>
            <View className='field'>
              <Text className='field__label'>持仓备注</Text>
              <Textarea className='field__textarea' value={form.note} placeholder='买入逻辑、观察条件…' onInput={(e) => setForm({ ...form, note: e.detail.value })} />
            </View>

            <View className='cost-preview'>
              <Text className='cost-preview__value'>预计占用 {money(estimatedCost)}</Text>
              <Text className='field__hint'>
                可用 {money(spendableFunds)} · 单股上限 {money(singleLimit)} · 总仓位上限 {money(investedLimit)}
              </Text>
            </View>

            {formError ? <Text className='loss modal__error'>{formError}</Text> : null}

            <View className='modal__actions'>
              <Button className='pill-btn pill-btn--ghost' onClick={() => setOpen(false)}>取消</Button>
              <Button className='pill-btn' loading={saving} onClick={() => void savePosition()}>{saving ? '保存中…' : '保存持仓'}</Button>
            </View>
          </View>
        </View>
      )}
    </ScrollView>
  )
}
