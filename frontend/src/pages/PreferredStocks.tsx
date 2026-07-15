import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { Button, PageHeader, Panel, StatusView, percent } from '../components/ui'
import type { PreferredStocksData } from '../types'

const amount = (value: number) => {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 亿`
  if (value >= 10_000) return `${(value / 10_000).toFixed(0)} 万`
  return value.toFixed(0)
}

export function PreferredStocks() {
  const [data, setData] = useState<PreferredStocksData>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await api.preferred())
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="page preferred-page">
      <PageHeader
        eyebrow="SELECTION RADAR · 优选个股"
        title="先缩小范围，再逐一求证"
        description="按热点主线、放量入场、短洗盘、价量重心和强势启动五项机器规则筛选；结果只是一份观察清单，不是买入建议。"
        actions={<Button tone="ghost" onClick={() => void load()} disabled={loading}>{loading ? '筛选中…' : '重新筛选'}</Button>}
      />

      <Panel className="screen-method">
        <div className="method-lead">
          <span>筛选路径</span>
          <strong>涨停主线 → 强势与流动性预筛 → 120 日 K 线验证</strong>
        </div>
        <ol>
          <li><b>01</b><span>主力入场有量</span></li>
          <li><b>02</b><span>洗盘短而可控</span></li>
          <li><b>03</b><span>价量重心上移</span></li>
          <li><b>04</b><span>强势启动信号</span></li>
          <li><b>05</b><span>处在活跃板块</span></li>
        </ol>
        <p>行业首板广度排名前三的热点板块自动进入评分；涨停池不可用时该项不计分。</p>
      </Panel>

      {loading ? <StatusView state="loading" message="正在预筛候选并逐只验证 K 线，首次加载可能需要十余秒" /> :
        error ? <StatusView state="error" message={error} onRetry={() => void load()} /> : data && (
          <>
            {data.source === 'sample' && (
              <div className="source-notice" role="status">
                <strong>停止筛选</strong>
                <span>实时行情暂不可用。系统不会使用模拟数据生成优选名单。</span>
              </div>
            )}
            {data.fallbackReason && data.source !== 'sample' && (
              <div className="source-notice" role="status">
                <strong>部分跳过</strong>
                <span>少量候选历史行情不可用，已自动排除，不影响下列已验证结果。</span>
              </div>
            )}
            <div className="screen-summary">
              <div><span>分析样本</span><strong>{data.analyzedCount}</strong><small>只 / 预筛候选</small></div>
              <div><span>进入清单</span><strong>{data.items.length}</strong><small>只 / 按分数排序</small></div>
              <div><span>评分口径</span><strong>5 × 20</strong><small>分 / 机器规则</small></div>
              <time>{data.updatedAt ? `更新于 ${new Date(data.updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '实时计算'}</time>
            </div>

            {!data.items.length ? <StatusView state="empty" message="当前没有通过数据验证的候选，请稍后再试" /> : (
              <section className="preferred-list" aria-label="优选个股观察清单">
                {data.items.map((stock, index) => (
                  <article className="preferred-card" key={stock.code}>
                    <div className="preferred-rank"><span>RANK</span><strong>{String(index + 1).padStart(2, '0')}</strong></div>
                    <div className="preferred-identity">
                      <small>{stock.code}</small>
                      <h2>{stock.name}</h2>
                      {stock.sector && <small className={stock.inMainline ? 'sector-tag active' : 'sector-tag'}>{stock.sector}{stock.inMainline ? ' · 主线' : ''}</small>}
                      <div>
                        <b>{stock.price.toFixed(2)}</b>
                        <em className={stock.change >= 0 ? 'gain' : 'loss'}>{percent(stock.change)}</em>
                        <span>成交额 {amount(stock.amount)}</span>
                      </div>
                    </div>
                    <div className="preferred-score">
                      <strong>{stock.score}</strong><span>/ 100</span>
                      <small className={`setup-${stock.setup === '重点观察' ? 'focus' : stock.setup === '继续跟踪' ? 'watch' : 'weak'}`}>{stock.setup}</small>
                    </div>
                    <ul className="preferred-checks">
                      {stock.checks.map((check) => (
                        <li key={check.key} className={check.status}>
                          <span>{check.status === 'passed' ? '✓' : check.status === 'manual' ? '?' : '×'}</span>
                          <div><b>{check.label}</b><small>{check.detail}</small></div>
                        </li>
                      ))}
                    </ul>
                    <div className="preferred-foot">
                      <p><span>洗盘周期</span><b>{stock.washoutDays ?? '—'} 日</b></p>
                      <p><span>最大回撤</span><b>{stock.pullbackPct != null ? `${stock.pullbackPct.toFixed(1)}%` : '—'}</b></p>
                      <p><span>启动低点止损参考</span><b>{stock.stopLoss?.toFixed(2) ?? '—'}</b></p>
                      <Link className="button button-ghost" to={`/stock?code=${stock.code}`}>打开个股诊断</Link>
                    </div>
                  </article>
                ))}
              </section>
            )}
          </>
        )}
    </div>
  )
}
