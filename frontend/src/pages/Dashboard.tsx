import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { Metric, PageHeader, Panel, StatusView, percent } from '../components/ui'
import type { MarketMainline, MarketOverview, MarketPhase, TodayBriefing } from '../types'

const seasons: Array<{ key: MarketPhase; name: string; cn: string; action: string }> = [
  { key: 'spring', name: '春', cn: '复苏', action: '试探布局' },
  { key: 'summer', name: '夏', cn: '繁荣', action: '顺势持有' },
  { key: 'autumn', name: '秋', cn: '降温', action: '收缩仓位' },
  { key: 'winter', name: '冬', cn: '冰点', action: '耐心等待' },
]

export function Dashboard() {
  const [data, setData] = useState<MarketOverview>()
  const [mainline, setMainline] = useState<MarketMainline>()
  const [briefing, setBriefing] = useState<TodayBriefing>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const todayP = api.today().then(setBriefing).catch(() => undefined)
    try {
      const [market, line] = await Promise.all([
        api.market(),
        api.mainline().catch(() => undefined),
      ])
      setData(market)
      setMainline(line)
      await todayP
    } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void api.today(true).then(setBriefing).catch(() => undefined)
    }, 4000)
    return () => window.clearTimeout(timer)
  }, [])
  const scanJob = briefing?.closeScreen.job
  useEffect(() => {
    if (scanJob?.status !== 'running') return
    const timer = window.setInterval(() => {
      void api.today(true).then(setBriefing).catch(() => undefined)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [scanJob?.status])

  return (
    <div className="page">
      <PageHeader
        eyebrow="MARKET TEMPERATURE · 市场体感"
        title="先观四时，再落一子"
        description="市场有温度，仓位有分寸。让趋势决定进退，不让情绪代替判断。"
        actions={data?.updatedAt && <span className="asof">更新于 {new Date(data.updatedAt).toLocaleTimeString('zh-CN')}</span>}
      />
      {briefing && (
        <section className="daily-brief" aria-label="今日行动">
          <div>
            <span>今日行动 · {briefing.session.label}</span>
            <strong>{briefing.session.action}</strong>
          </div>
          <ol>
            {briefing.stops.length ? briefing.stops.slice(0, 2).map((stop) => (
              <li key={stop.code}><b>止损</b><Link to={`/stock?code=${stop.code}`}>{stop.name}</Link> 已触发</li>
            )) : <li><b>止损</b>{briefing.positionCount ? '持仓暂无触发' : '当前空仓'}</li>}
            {briefing.discipline?.offList.length ? (
              <li>
                <b>纪律</b>
                今日买入不在清单：
                {briefing.discipline.offList.slice(0, 3).map((item) => (
                  <Link key={item.code} to={`/stock?code=${item.code}`}>{item.name}</Link>
                ))}
              </li>
            ) : briefing.discipline?.hasPlan && briefing.discipline.buyCount > 0 ? (
              <li><b>纪律</b>今日买入均在清单内</li>
            ) : null}
            {scanJob?.status === 'running' ? (
              <li>
                <b>扫描</b>
                <Link to="/preferred">
                  已验 {scanJob.checked ?? 0}/{scanJob.total ?? '…'}
                  {scanJob.matches != null ? ` · 通过 ${scanJob.matches}` : ''}
                </Link>
              </li>
            ) : briefing.closeScreen.needsRun && (
              <li>
                <b>今晚</b>
                <Link to="/preferred?run=1">收盘已过，运行今晚精选</Link>
              </li>
            )}
            {(briefing.session.code === 'after_close' || briefing.session.code === 'weekend') && !briefing.hasJournal && (
              <li>
                <b>复盘</b>
                <Link to="/review">写下今日一笔</Link>
              </li>
            )}
            <li>
              <b>{briefing.closeScreen.needsRun ? '上次' : '精选'}</b>
              {briefing.closeScreen.items.length
                ? briefing.closeScreen.items.slice(0, 3).map((item) => (
                  <Link key={item.code} to={`/stock?code=${item.code}`}>
                    {item.name}
                    {item.liveChange != null && (
                      <em className={item.liveChange >= 0 ? 'gain' : 'loss'}>{percent(item.liveChange)}</em>
                    )}
                  </Link>
                ))
                : <Link to="/preferred">尚未生成，去收盘筛选</Link>}
            </li>
          </ol>
        </section>
      )}
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
              <Metric label="炸板 / 量比" value={`${data.fried ?? 0} / ${(data.volumeRatio ?? 1).toFixed(2)}`} />
            </div>
          </section>

          <div className="season-line" aria-label="市场四季阶段">
            {seasons.map((season, index) => (
              <div key={season.key} className={season.key === data.phase ? 'season-node active' : 'season-node'}>
                <span>0{index + 1}</span><b>{season.name} · {season.cn}</b><small>{season.action}</small>
              </div>
            ))}
          </div>

          <Panel title="热点主线" eyebrow="FIRST BOARD · HOT / SECOND BOARD · LEADER">
            {mainline?.source === 'akshare' && mainline.sectors.length ? (
              <div className="mainline-layout">
                <div className="mainline-answer">
                  <span>今日主线</span>
                  <strong>{mainline.mainSector || '待确认'}</strong>
                  <small>
                    {mainline.activeSectors.length
                      ? `热点候选：${mainline.activeSectors.join(' · ')}`
                      : '涨停广度不足，暂不定义主线'}
                  </small>
                  <p>以行业首板广度定热点，以二板及以上连板高度定龙头候选。</p>
                </div>
                <div className="hot-sector-grid">
                  {mainline.sectors.slice(0, 6).map((sector, index) => (
                    <article key={sector.name} className={index === 0 ? 'hot-sector primary' : 'hot-sector'}>
                      <div><span>{String(index + 1).padStart(2, '0')}</span><b>{sector.name}</b></div>
                      <strong>{sector.limitUpCount}<small> 涨停</small></strong>
                      <p>首板 {sector.firstBoardCount} · 二板+ {sector.secondPlusCount} · 高度 {sector.maxBoard} 板</p>
                      {sector.leader && <em>领涨 {sector.leader.name} · {sector.leader.boardCount}板</em>}
                    </article>
                  ))}
                </div>
                <div className="leader-ladder">
                  <span>连板梯队 · 龙头候选</span>
                  {mainline.ladders.length ? mainline.ladders.map((ladder) => (
                    <div key={ladder.boardCount}>
                      <b>{ladder.boardCount} 板</b>
                      <p>{ladder.stocks.slice(0, 6).map((stock) => `${stock.name}（${stock.sector}）`).join(' · ')}</p>
                    </div>
                  )) : <p>今日暂无二板及以上股票，龙头尚未确认。</p>}
                </div>
              </div>
            ) : (
              <StatusView state="empty" message={mainline?.fallbackReason || '今日涨停明细暂不可用'} />
            )}
          </Panel>

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
