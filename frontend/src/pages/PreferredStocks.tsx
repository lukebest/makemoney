import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { Button, PageHeader, Panel, StatusView, percent } from '../components/ui'
import type { CloseScreenData, PreferredStock, PreferredStocksData } from '../types'

const amount = (value: number) => {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 亿`
  if (value >= 10_000) return `${(value / 10_000).toFixed(0)} 万`
  return value.toFixed(0)
}

function StockCards({ stocks, label }: { stocks: PreferredStock[]; label: string }) {
  if (!stocks.length) {
    return <StatusView state="empty" message="当前没有通过数据验证的候选，请稍后再试" />
  }
  return (
    <section className="preferred-list" aria-label={label}>
      {stocks.map((stock, index) => (
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
            <div className="preferred-actions">
              <Link className="button button-ghost" to={`/stock?code=${stock.code}`}>打开个股诊断</Link>
              <Link
                className="button button-ghost"
                to={`/trades?code=${encodeURIComponent(stock.code)}&name=${encodeURIComponent(stock.name)}&price=${stock.price}&stop=${stock.stopLoss ?? ''}`}
              >
                记入交易台
              </Link>
            </div>
          </div>
        </article>
      ))}
    </section>
  )
}

export function PreferredStocks() {
  const [params, setParams] = useSearchParams()
  const autoRun = useRef(false)
  const [data, setData] = useState<PreferredStocksData>()
  const [closeScreen, setCloseScreen] = useState<CloseScreenData>()
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState('')
  const [scanError, setScanError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const preferredP = api.preferred()
    try {
      const saved = await api.closeScreen()
      setCloseScreen(saved)
      if (saved.job?.status === 'running') {
        setScanning(true)
        void api.runCloseScreen(setCloseScreen)
          .then(setCloseScreen)
          .catch((reason) => setScanError(errorMessage(reason)))
          .finally(() => setScanning(false))
      }
    } catch (reason) {
      setScanError(errorMessage(reason))
    }
    try {
      const preferred = await preferredP
      setData(preferred)
      if (preferred.stale) {
        window.setTimeout(() => {
          void api.preferred().then((fresh) => {
            if (!fresh.stale) setData(fresh)
          }).catch(() => undefined)
        }, 3000)
      }
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  const runCloseScreen = useCallback(async () => {
    setScanning(true)
    setScanError('')
    try {
      setCloseScreen(await api.runCloseScreen(setCloseScreen))
    } catch (reason) {
      setScanError(errorMessage(reason))
    } finally {
      setScanning(false)
    }
  }, [])

  const rejectSummary = closeScreen
    ? Object.entries(closeScreen.rejectedBy)
      .sort((left, right) => right[1] - left[1])
      .slice(0, 3)
      .map(([key, count]) => `${key} ${count}`)
      .join(' · ')
    : ''
  const job = closeScreen?.job
  const scanLabel = scanning && job?.total
    ? `已验 ${job.checked ?? 0}/${job.total} · 通过 ${job.matches ?? 0}`
    : scanning
      ? '后台扫描中，可先看上次结果…'
      : '运行收盘筛选'

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (autoRun.current || params.get('run') !== '1' || scanning || !closeScreen?.needsRun) return
    autoRun.current = true
    setParams({}, { replace: true })
    void runCloseScreen()
  }, [closeScreen, params, runCloseScreen, scanning, setParams])

  const watchCodes = (closeScreen?.items ?? []).slice(0, 5).map((stock) => stock.code).join(',')
  useEffect(() => {
    if (!watchCodes) return
    for (const code of watchCodes.split(',')) {
      void api.stock(code).catch(() => undefined)
    }
  }, [watchCodes])

  return (
    <div className="page preferred-page">
      <PageHeader
        eyebrow="SELECTION RADAR · 优选个股"
        title="先缩小范围，再逐一求证"
        description="按热点主线、放量入场、短洗盘、价量重心和强势启动五项机器规则筛选；结果只是一份观察清单，不是买入建议。"
        actions={<Button tone="ghost" onClick={() => void load()} disabled={loading}>{loading ? '筛选中…' : '重新筛选'}</Button>}
      />

      <Panel className="close-screen-panel">
        <div className="close-screen-head">
          <div>
            <span>收盘精选 · 五项全过</span>
            <strong>热点行业全成分 → 短路过滤</strong>
            <p>
              {closeScreen?.asOfDate && closeScreen?.forDate
                ? `基于 ${closeScreen.asOfDate} 收盘（${closeScreen.sessionKind === 'previous_close' ? '上一交易日' : '当日'}），面向 ${closeScreen.forDate} 交易日`
                : '随时可运行：15:00 后用当日收盘，此前自动改用上一交易日收盘；首次扫描可能需要一两分钟'}
            </p>
          </div>
          <Button onClick={() => void runCloseScreen()} disabled={scanning}>
            {scanLabel}
          </Button>
        </div>
        {scanError && <StatusView state="error" message={scanError} onRetry={() => void runCloseScreen()} />}
        {!scanError && closeScreen && (
          <div className="screen-summary close-screen-summary">
            <div><span>行业宇宙</span><strong>{closeScreen.universeCount}</strong><small>只 / 热点成分</small></div>
            <div><span>进入验线</span><strong>{closeScreen.analyzedCount}</strong><small>只 / 流动性过门</small></div>
            <div><span>五项全过</span><strong>{closeScreen.matchCount}</strong><small>只 / 次日观察</small></div>
            <time>
              {rejectSummary ? `主要淘汰：${rejectSummary}` : closeScreen.updatedAt
                ? `保存于 ${new Date(closeScreen.updatedAt).toLocaleString('zh-CN')}`
                : '尚未保存'}
            </time>
          </div>
        )}
        {!scanError && closeScreen && (
          closeScreen.items.length
            ? <StockCards stocks={closeScreen.items} label="收盘精选五项全过" />
            : <StatusView state="empty" message="最近一次收盘筛选没有五项全过的标的" />
        )}
      </Panel>

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
        <p>行业首板广度排名前三的热点板块自动进入评分；涨停池不可用时该项不计分。收盘筛选会覆盖热点行业全部成分股，并按易否决条件短路加速。</p>
      </Panel>

      {loading ? <StatusView state="loading" message="正在预筛候选并验证 K 线" /> :
        error ? <StatusView state="error" message={error} onRetry={() => void load()} /> : data && (
          <>
            <div className="screen-summary">
              <div><span>盘中观察</span><strong>{data.analyzedCount}</strong><small>只 / 预筛候选</small></div>
              <div><span>进入清单</span><strong>{data.items.length}</strong><small>只 / 按分数排序</small></div>
              <div><span>评分口径</span><strong>5 × 20</strong><small>分 / 机器规则</small></div>
              <time>{data.updatedAt ? `更新于 ${new Date(data.updatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '实时计算'}</time>
            </div>
            {data.stale && (
              <div className="source-notice" role="status">
                <strong>名单刷新中</strong>
                <span>先显示上次结果，后台正在按最新行情重算。</span>
              </div>
            )}
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
            <StockCards stocks={data.items} label="优选个股观察清单" />
          </>
        )}
    </div>
  )
}
