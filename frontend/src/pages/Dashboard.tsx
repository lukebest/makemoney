import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { Metric, PageHeader, Panel, StatusView, percent } from '../components/ui'
import type { MarketOverview, MarketPhase } from '../types'

const seasons: Array<{ key: MarketPhase; name: string; cn: string; action: string }> = [
  { key: 'spring', name: '春', cn: '复苏', action: '试探布局' },
  { key: 'summer', name: '夏', cn: '繁荣', action: '顺势持有' },
  { key: 'autumn', name: '秋', cn: '降温', action: '收缩仓位' },
  { key: 'winter', name: '冬', cn: '冰点', action: '耐心等待' },
]

export function Dashboard() {
  const [data, setData] = useState<MarketOverview>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try { setData(await api.market()) } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  return (
    <div className="page">
      <PageHeader
        eyebrow="MARKET TEMPERATURE · 市场体感"
        title="先观四时，再落一子"
        description="市场有温度，仓位有分寸。让趋势决定进退，不让情绪代替判断。"
        actions={data?.updatedAt && <span className="asof">更新于 {new Date(data.updatedAt).toLocaleTimeString('zh-CN')}</span>}
      />
      {loading ? <StatusView state="loading" /> : error ? <StatusView state="error" message={error} onRetry={load} /> : !data ? <StatusView state="empty" /> : (
        <>
          {data.source === 'sample' && (
            <div className="source-notice" role="status">
              <strong>演示行情</strong>
              <span>实时数据源暂不可用，当前数字仅用于体验界面，不能作为交易依据。</span>
            </div>
          )}
          <section className="temperature-hero">
            <div className="temperature-gauge">
              <div className="gauge-ring" style={{ '--score': `${Math.min(100, Math.max(0, data.score)) * 3.6}deg` } as React.CSSProperties}>
                <div><strong>{data.score}</strong><span>市场温度</span></div>
              </div>
            </div>
            <div className="season-copy">
              <span className={`season-stamp phase-${data.phase}`}>{seasons.find((s) => s.key === data.phase)?.name || '观'}</span>
              <div>
                <p className="eyebrow">CURRENT PHASE</p>
                <h2>{data.phaseLabel || seasons.find((s) => s.key === data.phase)?.cn || '观望期'}</h2>
                <p>{data.summary || '保持观察，等待趋势给出清晰方向。'}</p>
              </div>
            </div>
            <div className="breadth">
              <Metric label="上涨家数" value={data.advance ?? 0} tone="gain" />
              <Metric label="下跌家数" value={data.decline ?? 0} tone="loss" />
              <Metric label="涨 / 跌停" value={`${data.limitUp ?? 0} / ${data.limitDown ?? 0}`} />
            </div>
          </section>

          <div className="season-line" aria-label="市场四季阶段">
            {seasons.map((season, index) => (
              <div key={season.key} className={season.key === data.phase ? 'season-node active' : 'season-node'}>
                <span>0{index + 1}</span><b>{season.name} · {season.cn}</b><small>{season.action}</small>
              </div>
            ))}
          </div>

          <Panel title="核心指数" eyebrow="INDEX PULSE">
            {data.indices?.length ? <div className="index-grid">
              {data.indices.map((item) => (
                <article className="index-card" key={item.code}>
                  <div><span>{item.name}</span><small>{item.code}</small></div>
                  <strong>{Number(item.value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</strong>
                  <em className={item.change >= 0 ? 'gain' : 'loss'}>{percent(item.change)}</em>
                  <i className={item.change >= 0 ? 'spark gain-bg' : 'spark loss-bg'} />
                </article>
              ))}
            </div> : <StatusView state="empty" message="暂无指数行情" />}
          </Panel>
        </>
      )}
    </div>
  )
}
