import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import type { EChartsOption } from 'echarts'
import { api, errorMessage } from '../api'
import { AICoach } from '../components/AICoach'
import { Chart } from '../components/Chart'
import { Button, Metric, PageHeader, Panel, StatusView, percent } from '../components/ui'
import type { KlineBar, StockAnalysis as StockAnalysisData } from '../types'

const ma = (bars: KlineBar[], days: number) =>
  bars.map((bar, index) => {
    const explicit = bar[`ma${days}` as keyof KlineBar]
    if (typeof explicit === 'number') return explicit
    if (index < days - 1) return null
    return Number((bars.slice(index - days + 1, index + 1).reduce((sum, item) => sum + item.close, 0) / days).toFixed(2))
  })

export function StockAnalysis() {
  const [code, setCode] = useState('')
  const [data, setData] = useState<StockAnalysisData>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const analyze = useCallback(async (value: string) => {
    const normalized = value.trim().toUpperCase()
    if (!/^(?:\d{5}|\d{6}|(?:SH|SZ)\d{6}|HK\d{5})$/.test(normalized)) {
      setError('请输入 6 位 A 股或 5 位港股代码，例如 600519、00700')
      return
    }
    setLoading(true)
    setError('')
    try { setData(await api.stock(normalized.replace(/^(SH|SZ|HK)/, ''))) } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])

  function submit(event: FormEvent) {
    event.preventDefault()
    void analyze(code)
  }

  useEffect(() => {
    const initialCode = new URLSearchParams(window.location.search).get('code')
    if (initialCode) {
      setCode(initialCode)
      void analyze(initialCode)
    }
  }, [analyze])

  const chartOption = useMemo<EChartsOption>(() => {
    if (!data?.klines?.length) return {}
    const bars = data.klines
    const axisCommon = {
      axisLine: { lineStyle: { color: '#4a463c' } },
      axisLabel: { color: '#8d887c', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(178,151,91,.1)' } },
    }
    return {
      animation: true,
      backgroundColor: 'transparent',
      legend: { top: 2, right: 8, textStyle: { color: '#aaa396' }, data: ['MA5', 'MA10', 'MA20', 'MA60'] },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross', lineStyle: { color: '#b2975b' } }, backgroundColor: '#11130f', borderColor: '#665b42', textStyle: { color: '#eee7d6' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#7d6841' } },
      grid: [{ left: 54, right: 18, top: 38, height: '58%' }, { left: 54, right: 18, top: '75%', height: '14%' }],
      xAxis: [
        { ...axisCommon, type: 'category', data: bars.map((bar) => bar.date), boundaryGap: true, axisLabel: { ...axisCommon.axisLabel, show: false } },
        { ...axisCommon, type: 'category', gridIndex: 1, data: bars.map((bar) => bar.date), boundaryGap: true },
      ],
      yAxis: [
        { ...axisCommon, scale: true, splitNumber: 4 },
        { ...axisCommon, scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { ...axisCommon.axisLabel, formatter: (value: number) => `${Math.round(value / 10000)}万` } },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: Math.max(0, 100 - 6000 / bars.length), end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], bottom: 2, height: 18, borderColor: '#3c392f', fillerColor: 'rgba(178,151,91,.2)', handleStyle: { color: '#b2975b' }, textStyle: { color: '#777268' } },
      ],
      series: [
        {
          name: 'K线', type: 'candlestick', data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
          itemStyle: { color: '#b93a32', color0: '#3d8b6d', borderColor: '#d35449', borderColor0: '#57a987' },
        },
        ...[
          ['MA5', 5, '#d9b85f'], ['MA10', 10, '#b98dc0'], ['MA20', 20, '#5da5b8'], ['MA60', 60, '#eee7d6'],
        ].map(([name, days, color]) => ({
          name, type: 'line', data: ma(bars, Number(days)), smooth: true, symbol: 'none',
          lineStyle: { width: 1.2, color }, emphasis: { focus: 'series' },
        })),
        {
          name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
          data: bars.map((bar) => ({ value: bar.volume, itemStyle: { color: bar.close >= bar.open ? 'rgba(185,58,50,.65)' : 'rgba(61,139,109,.65)' } })),
        },
      ],
    } as EChartsOption
  }, [data])

  return (
    <div className="page">
      <PageHeader eyebrow="STOCK DIAGNOSIS · 个股诊断" title="不预测，只确认" description="支持 A 股与港股（含港股通标的），观察价格、均线与成交量是否说着同一种语言。" />
      <form className="stock-search" onSubmit={submit}>
        <label htmlFor="stock-code">股票代码</label>
        <input id="stock-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="A股 600519 / 港股通 00700" inputMode="numeric" maxLength={8} />
        <Button type="submit" disabled={loading}>{loading ? '诊断中…' : '开始诊断'}</Button>
      </form>
      {loading ? <StatusView state="loading" /> : error ? <StatusView state="error" message={error} /> : !data ? (
        <div className="analysis-placeholder"><span>析</span><p>键入股票代码<br /><small>让数据先开口</small></p></div>
      ) : (
        <>
          {data.source === 'sample' && (
            <div className="source-notice" role="status">
              <strong>演示行情</strong>
              <span>akshare 上游暂不可用，当前 K 线为模拟数据，不能作为交易依据。</span>
            </div>
          )}
          {data.source === 'partial' && (data.klines?.length ?? 0) <= 5 && (
            <div className="source-notice" role="status">
              <strong>新股 / 日线不足</strong>
              <span>{data.fallbackReason || '历史日线暂不可用，仅展示当日真实行情；均线与结构信号暂不可靠。'}</span>
            </div>
          )}
          {data.source === 'partial' && (data.klines?.length ?? 0) > 5 && (
            <div className="source-notice" role="status">
              <strong>行情延迟</strong>
              <span>实时现价暂不可用，当前价格为最近交易日收盘价；K 线仍为真实历史数据。</span>
            </div>
          )}
          {data.source === 'akshare' && (data.klines?.length ?? 0) > 0 && (data.klines?.length ?? 0) < 20 && (
            <div className="source-notice" role="status">
              <strong>历史偏短</strong>
              <span>仅有 {data.klines.length} 个交易日（常见于新股），均线与结构信号仅供参考。</span>
            </div>
          )}
          <section className="stock-ticker">
            <div><p>{data.code}{data.market === 'HK' ? ' · 港股' : ''}</p><h2>{data.name}</h2></div>
            <Metric label={`现价 · ${data.currency || 'CNY'}`} value={Number(data.price).toFixed(2)} />
            <Metric label="涨跌幅" value={percent(data.change)} tone={data.change >= 0 ? 'gain' : 'loss'} />
            <Metric label="趋势判定" value={data.trend || '待确认'} note={data.score != null ? `强度 ${data.score}` : undefined} />
          </section>
          <Panel title="量价结构" eyebrow="PRICE · VOLUME" className="chart-panel">
            {data.klines?.length ? <Chart option={chartOption} ariaLabel={`${data.name} K线、均线和成交量图`} className="stock-chart" /> : <StatusView state="empty" message="暂无K线数据" />}
          </Panel>
          {data.structure && (
            <Panel title="主力阶段与承接" eyebrow="STRUCTURE · ACCEPTANCE">
              <div className="structure-cards">
                <article className={`structure-card phase-${data.structure.phase}`}>
                  <span>量价阶段</span>
                  <h3>{data.structure.label}</h3>
                  <p>{data.structure.summary}</p>
                  <ul>{data.structure.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
                </article>
                <article className={`structure-card acceptance-${data.structure.acceptance.code}`}>
                  <span>买卖承接</span>
                  <h3>{data.structure.acceptance.label}</h3>
                  <p>{data.structure.acceptance.summary}</p>
                  {(data.structure.acceptance.change3dPct != null || data.structure.acceptance.volumeRatio != null) && (
                    <small>
                      近3日涨跌 {data.structure.acceptance.change3dPct?.toFixed(1) ?? '—'}%
                      {' · '}量比 {data.structure.acceptance.volumeRatio?.toFixed(2) ?? '—'}
                    </small>
                  )}
                </article>
              </div>
              <p className="structure-disclaimer">“建仓、洗盘、拉升、出货”均为量价规则的疑似判定，不代表已识别真实交易主体或主力意图。</p>
            </Panel>
          )}
          <div className="analysis-grid">
            <Panel title="趋势结论" eyebrow="VERDICT">
              <p className="verdict">{data.summary || data.trend || '趋势信号尚不充分，继续观察。'}</p>
              {(data.support || data.resistance) && (
                <p className="price-levels">
                  近20日支撑 <b>{Number(data.support || 0).toFixed(2)}</b>
                  <span>·</span>
                  压力 <b>{Number(data.resistance || 0).toFixed(2)}</b>
                </p>
              )}
              {data.chanPivot && (
                <p className="price-levels">
                  缠论中枢 <b>{data.chanPivot.zd.toFixed(2)} ~ {data.chanPivot.zg.toFixed(2)}</b>
                  <span>·</span>
                  {data.chanPivot.startDate} 起
                </p>
              )}
              {data.chanThirdBuy && (
                <p className="chan-signal">
                  {data.chanThirdBuy.date} 出现类三买结构：突破中枢上沿 {data.chanThirdBuy.zg.toFixed(2)} 后，
                  回踩 {data.chanThirdBuy.pullbackLow.toFixed(2)} 未回中枢。若跌回中枢内则信号作废。
                </p>
              )}
              {data.source !== 'sample' && (
                <AICoach
                  label="AI 解读这些信号"
                  busyLabel="Grok 正在解读…"
                  hint="基于上方机器信号生成，不构成投资建议"
                  run={() => api.aiInterpret(data.code)}
                />
              )}
            </Panel>
            <Panel title="入场检查" eyebrow="DISCIPLINE CHECK">
              {data.checks?.length ? <ul className="check-list">{data.checks.map((item, i) => (
                <li key={`${item.label}-${i}`} className={item.passed ? 'passed' : 'failed'}><span>{item.passed ? '✓' : '×'}</span><div><b>{item.label}</b>{item.detail && <small>{item.detail}</small>}</div></li>
              ))}</ul> : <StatusView state="empty" message="暂无检查项" />}
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}
