import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import type { EChartsOption } from 'echarts'
import { api, errorMessage } from '../api'
import { Chart } from '../components/Chart'
import { Button, Metric, PageHeader, Panel, StatusView, money, percent } from '../components/ui'
import type { Position, PositionInput, Settings } from '../types'

const emptyForm: PositionInput = { code: '', name: '', quantity: 0, costPrice: 0, currentPrice: 0, stopPrice: 0, tier: 1, note: '' }

export function Positions() {
  const [positions, setPositions] = useState<Position[]>([])
  const [settings, setSettings] = useState<Settings>({ totalCapital: 0 })
  const [form, setForm] = useState<PositionInput>(emptyForm)
  const [editingId, setEditingId] = useState<Position['id']>()
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [positionData, settingData] = await Promise.all([api.positions(), api.settings()])
      setPositions(positionData)
      setSettings({ totalCapital: Number(settingData.totalCapital ?? (settingData as unknown as { total_capital?: number }).total_capital ?? 0) })
    } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  const marketValue = positions.reduce((sum, position) => sum + position.quantity * (position.currentPrice || position.costPrice), 0)
  const cost = positions.reduce((sum, position) => sum + position.quantity * position.costPrice, 0)
  const pnl = marketValue - cost
  const stopAlerts = positions.filter((position) => position.stopPrice > 0 && position.currentPrice <= position.stopPrice)
  const bottomValue = positions.filter((p) => p.tier === 1).reduce((sum, p) => sum + p.quantity * (p.currentPrice || p.costPrice), 0)
  const activeValue = positions.filter((p) => p.tier !== 1).reduce((sum, p) => sum + p.quantity * (p.currentPrice || p.costPrice), 0)
  const allocationWarnings = settings.totalCapital > 0
    ? [
      bottomValue > settings.totalCapital * .3 ? '底仓超过30%' : '',
      activeValue > settings.totalCapital * .3 ? '机动仓超过30%' : '',
      marketValue > settings.totalCapital * .6 ? '现金预备队低于40%' : '',
    ].filter(Boolean)
    : []

  const donutOption = useMemo<EChartsOption>(() => {
    const cash = Math.max(0, settings.totalCapital - marketValue)
    return {
      tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 元 · {d}%' },
      legend: { bottom: 0, textStyle: { color: '#aaa396' }, itemWidth: 8, itemHeight: 8 },
      series: [{
        name: '仓位结构', type: 'pie', radius: ['52%', '74%'], center: ['50%', '43%'], padAngle: 2,
        label: { show: false }, emphasis: { scaleSize: 6 },
        data: [
          { value: bottomValue, name: '底仓 · 目标30%', itemStyle: { color: '#b93a32' } },
          { value: activeValue, name: '机动仓 · 目标30%', itemStyle: { color: '#b2975b' } },
          { value: cash, name: '现金 · 目标40%', itemStyle: { color: '#536f62' } },
        ],
      }],
      graphic: [{ type: 'text', left: 'center', top: '37%', style: { text: settings.totalCapital ? `${Math.round(marketValue / settings.totalCapital * 100)}%` : '0%', fill: '#eee7d6', font: '600 24px serif', textAlign: 'center' } }],
    }
  }, [activeValue, bottomValue, marketValue, settings.totalCapital])

  async function saveCapital(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try { setSettings(await api.updateSettings(settings)) } catch (e) { setError(errorMessage(e)) }
  }

  function beginEdit(position?: Position) {
    if (position) {
      setEditingId(position.id)
      setForm({
        code: position.code, name: position.name, quantity: position.quantity, costPrice: position.costPrice,
        currentPrice: position.currentPrice, stopPrice: position.stopPrice, tier: position.tier, note: position.note || '',
      })
    } else { setEditingId(undefined); setForm(emptyForm) }
    setOpen(true)
  }

  async function savePosition(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      if (editingId != null) await api.updatePosition(editingId, form)
      else await api.createPosition(form)
      setOpen(false)
      await load()
    } catch (e) { setError(errorMessage(e)) } finally { setSaving(false) }
  }

  async function remove(position: Position) {
    if (!window.confirm(`确认删除 ${position.name || position.code} 的持仓？`)) return
    try { await api.deletePosition(position.id); await load() } catch (e) { setError(errorMessage(e)) }
  }

  return (
    <div className="page">
      <PageHeader eyebrow="POSITION CONTROL · 仓位管理" title="仓位，是生存的刻度" description="用 3 · 3 · 4 结构限制冲动。先决定最多亏多少，再决定可以买多少。" actions={<Button onClick={() => beginEdit()}>＋ 新增持仓</Button>} />
      {error && <div className="inline-error" role="alert">{error}<button onClick={() => setError('')} aria-label="关闭错误">×</button></div>}
      {loading ? <StatusView state="loading" /> : (
        <>
          <div className="capital-grid">
            <Panel className="capital-summary">
              <form onSubmit={saveCapital} className="capital-form">
                <label htmlFor="capital">账户总资金</label>
                <div><span>¥</span><input id="capital" type="number" min="0" step="1000" value={settings.totalCapital || ''} onChange={(e) => setSettings({ ...settings, totalCapital: Number(e.target.value) })} /><Button tone="ghost" type="submit">保存</Button></div>
              </form>
              <div className="metric-row">
                <Metric label="持仓市值" value={money(marketValue)} />
                <Metric label="浮动盈亏" value={money(pnl)} tone={pnl >= 0 ? 'gain' : 'loss'} note={cost ? percent(pnl / cost * 100) : '0.00%'} />
                <Metric label="可用现金" value={money(Math.max(0, settings.totalCapital - marketValue))} />
              </div>
            </Panel>
            <Panel title="三三四仓位结构" eyebrow="ALLOCATION"><Chart option={donutOption} className="donut-chart" ariaLabel="三三四仓位配置环形图" /></Panel>
          </div>

          {stopAlerts.length > 0 && <div className="stop-alert" role="alert"><strong>止损线触发 · {stopAlerts.length} 只</strong><span>{stopAlerts.map((item) => item.name || item.code).join('、')} 已触及预设退出价，请按纪律处置。</span></div>}
          {allocationWarnings.length > 0 && <div className="allocation-alert" role="alert"><strong>仓位纪律提醒</strong><span>{allocationWarnings.join('；')}。首次开仓永远不满仓，永远保留预备队。</span></div>}

          <Panel title={`当前持仓 · ${positions.length}`} eyebrow="OPEN POSITIONS">
            {!positions.length ? <StatusView state="empty" message="新增第一笔持仓，开始记录风险" /> : <div className="table-wrap"><table>
              <thead><tr><th>标的</th><th>层级</th><th>数量</th><th>成本 / 现价</th><th>市值</th><th>盈亏</th><th>止损价</th><th><span className="sr-only">操作</span></th></tr></thead>
              <tbody>{positions.map((p) => {
                const itemPnl = (p.currentPrice - p.costPrice) * p.quantity
                const warning = p.stopPrice > 0 && p.currentPrice <= p.stopPrice
                return <tr key={p.id} className={warning ? 'warning-row' : ''}>
                  <td><b>{p.name || '未命名'}</b><small>{p.code}</small></td>
                  <td><span className={`tier tier-${p.tier}`}>{p.tier === 1 ? '底仓' : '机动'}</span></td>
                  <td>{p.quantity.toLocaleString()}</td>
                  <td>{p.costPrice.toFixed(2)} <i>/</i> {p.currentPrice.toFixed(2)}</td>
                  <td>{money(p.quantity * p.currentPrice)}</td>
                  <td className={itemPnl >= 0 ? 'gain' : 'loss'}>{money(itemPnl)}</td>
                  <td className={warning ? 'gain' : ''}>{p.stopPrice.toFixed(2)}{warning && <small> 已触发</small>}</td>
                  <td className="row-actions"><Button tone="ghost" onClick={() => beginEdit(p)}>编辑</Button><Button tone="danger" onClick={() => void remove(p)}>删除</Button></td>
                </tr>
              })}</tbody>
            </table></div>}
          </Panel>
        </>
      )}

      {open && <div className="dialog-backdrop" onMouseDown={(e) => { if (e.currentTarget === e.target) setOpen(false) }}>
        <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="position-dialog-title">
          <div className="dialog-head"><div><span>POSITION LEDGER</span><h2 id="position-dialog-title">{editingId != null ? '编辑持仓' : '新增持仓'}</h2></div><button onClick={() => setOpen(false)} aria-label="关闭">×</button></div>
          <form className="form-grid" onSubmit={savePosition}>
            <label>股票代码<input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="600519" /></label>
            <label>股票名称<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="贵州茅台" /></label>
            <label>持有数量<input required type="number" min="1" value={form.quantity || ''} onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })} /></label>
            <label>持仓层级<select value={form.tier} onChange={(e) => setForm({ ...form, tier: Number(e.target.value) as 1 | 2 })}><option value="1">底仓 · 目标30%</option><option value="2">机动仓 · 目标30%</option></select></label>
            <label>成本价<input required type="number" min="0.01" step="0.01" value={form.costPrice || ''} onChange={(e) => {
              const costPrice = Number(e.target.value)
              setForm({ ...form, costPrice, stopPrice: form.stopPrice || Number((costPrice * .95).toFixed(2)) })
            }} /></label>
            <label className="accent-field">止损价<input required type="number" min="0.01" step="0.01" max={form.costPrice || undefined} value={form.stopPrice || ''} onChange={(e) => setForm({ ...form, stopPrice: Number(e.target.value) })} /><small>默认成本价下方 5%，可按策略调整</small></label>
            <label className="full">持仓备注<textarea rows={3} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="买入逻辑、观察条件…" /></label>
            <div className="dialog-actions full"><Button type="button" tone="ghost" onClick={() => setOpen(false)}>取消</Button><Button type="submit" disabled={saving}>{saving ? '保存中…' : '保存持仓'}</Button></div>
          </form>
        </section>
      </div>}
    </div>
  )
}
