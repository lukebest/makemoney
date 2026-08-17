import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import type { EChartsOption } from 'echarts'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { AICoach } from '../components/AICoach'
import { Chart } from '../components/Chart'
import { Button, Metric, PageHeader, Panel, StatusView, money, percent } from '../components/ui'
import type { JournalEntry, ReviewData, TodayBriefing } from '../types'

const chinaDay = (value?: string) => {
  if (!value) return ''
  try {
    return new Date(value).toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
  } catch {
    return value.slice(0, 10)
  }
}

const defaultMistakes = [
  '把投资当业余爱好，却期待专业收益', '三分钟草率审查一只股票', '野心很大，耐性不足',
  '假装勤奋，缺少真正思考', '只买生，不买熟', '买时过度自信，买后过度恐慌',
  '机械套用技术止损', '追求确定性和精准买点', '知识碎片化', '靠意念炒股',
]

function initialChecks() {
  try { return new Set<string>(JSON.parse(localStorage.getItem('fatal-mistake-checks') || '[]')) } catch { return new Set<string>() }
}

export function Review() {
  const [data, setData] = useState<ReviewData>()
  const [briefing, setBriefing] = useState<TodayBriefing>()
  const [checks, setChecks] = useState<Set<string>>(initialChecks)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [journals, setJournals] = useState<JournalEntry[]>([])
  const [note, setNote] = useState('')
  const [noteId, setNoteId] = useState<number>()
  const [savingNote, setSavingNote] = useState(false)
  const [noteMessage, setNoteMessage] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    void api.today(true).then(setBriefing).catch(() => undefined)
    void api.journals().then((items) => {
      setJournals(items)
      const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
      const current = items.find((item) => chinaDay(item.createdAt) === today)
      if (current) {
        setNoteId(current.id)
        setNote(current.content)
      }
    }).catch(() => undefined)
    try { setData(await api.review()) } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  const monthlyOption = useMemo<EChartsOption>(() => {
    const monthly = data?.monthly || []
    return {
      tooltip: { trigger: 'axis', backgroundColor: '#11130f', borderColor: '#665b42', textStyle: { color: '#eee7d6' }, valueFormatter: (value) => money(Number(value)) },
      grid: { left: 64, right: 18, top: 26, bottom: 40 },
      xAxis: { type: 'category', data: monthly.map((item) => item.month), axisLine: { lineStyle: { color: '#4a463c' } }, axisLabel: { color: '#8d887c' } },
      yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: '#8d887c', formatter: (value: number) => Math.abs(value) >= 1000 ? `${(value / 1000).toFixed(1)}k` : `¥${value}` }, splitLine: { lineStyle: { color: 'rgba(178,151,91,.1)' } } },
      series: [{
        type: 'bar', barMaxWidth: 30,
        data: monthly.map((item) => ({ value: item.profit, itemStyle: { color: item.profit >= 0 ? '#b93a32' : '#3d8b6d', borderRadius: item.profit >= 0 ? [2, 2, 0, 0] : [0, 0, 2, 2] } })),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#5a554a', type: 'dashed' }, data: [{ yAxis: 0 }] },
      }],
    }
  }, [data])

  function toggleMistake(item: string) {
    const next = new Set(checks)
    if (next.has(item)) next.delete(item); else next.add(item)
    setChecks(next)
    localStorage.setItem('fatal-mistake-checks', JSON.stringify([...next]))
  }

  const mistakes = data?.fatalMistakes?.length ? data.fatalMistakes : defaultMistakes
  const todayStamp = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
  const pastNotes = journals.filter((item) => item.id !== noteId).slice(0, 3)

  async function saveNote(event: FormEvent) {
    event.preventDefault()
    if (!note.trim()) return
    setSavingNote(true)
    setNoteMessage('')
    try {
      const saved = await api.saveJournal({
        id: noteId,
        title: `${todayStamp} 收盘复盘`,
        content: note.trim(),
      })
      setNoteId(saved.id)
      setNote(saved.content)
      setNoteMessage('今日一笔已记下')
      setJournals(await api.journals())
    } catch (reason) {
      setNoteMessage(errorMessage(reason))
    } finally {
      setSavingNote(false)
    }
  }

  return (
    <div className="page">
      <PageHeader eyebrow="CLOSING REVIEW · 收盘复盘" title="把结果交给统计，把错误留在今天" description="复盘不是审判盈亏，而是检查过程。持续记录，才能分清运气与能力。" />
      {briefing && (briefing.closeScreen.needsRun || briefing.closeScreen.items.length || briefing.discipline?.buyCount) ? (
        <section className="daily-brief" aria-label="精选回顾">
          <div>
            <span>{briefing.closeScreen.needsRun ? '精选回顾' : '明日观察'} · {briefing.closeScreen.asOfDate || '尚未筛选'}</span>
            <strong>
              {briefing.closeScreen.needsRun ? '昨夜五项全过，今日怎么走' : '今晚精选，下一交易日只做清单内的票'}
            </strong>
          </div>
          <ol>
            {briefing.discipline?.offList.length ? (
              <li>
                <b>纪律</b>
                今日买入不在清单：
                {briefing.discipline.offList.slice(0, 3).map((item) => (
                  <Link key={item.code} to={`/trades?code=${item.code}`}>{item.name}</Link>
                ))}
              </li>
            ) : briefing.discipline?.hasPlan && briefing.discipline.buyCount > 0 ? (
              <li><b>纪律</b>今日买入均在清单内</li>
            ) : null}
            {briefing.closeScreen.needsRun && (
              <li>
                <b>今晚</b>
                <Link to="/preferred?run=1">收盘已过，运行今晚精选</Link>
              </li>
            )}
            {briefing.closeScreen.items.length
              ? briefing.closeScreen.items.slice(0, 5).map((item) => (
                <li key={item.code}>
                  <b>{item.score}</b>
                  <Link to={`/stock?code=${item.code}`}>{item.name}</Link>
                  {item.liveChange != null
                    ? <em className={item.liveChange >= 0 ? 'gain' : 'loss'}>{percent(item.liveChange)}</em>
                    : briefing.closeScreen.needsRun ? <span>待行情</span> : null}
                </li>
              ))
              : !briefing.closeScreen.needsRun && (
                <li><Link to="/preferred">尚未生成，去收盘筛选</Link></li>
              )}
          </ol>
        </section>
      ) : null}
      <Panel title="今日一笔" eyebrow="DAILY NOTE">
        <p className="check-intro">收盘后用几句话写下过程，不写盈亏故事。有清单外买入时，先写为什么破例。</p>
        <form className="trade-form" onSubmit={(event) => void saveNote(event)}>
          <label className="sell-reason">
            <textarea
              required
              rows={4}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="今天守住了什么，又在哪里松了一下…"
            />
          </label>
          {noteMessage && (
            <p className={`form-message ${noteMessage === '今日一笔已记下' ? 'success' : 'error'}`} role="status">
              {noteMessage}
            </p>
          )}
          <Button type="submit" disabled={savingNote}>{savingNote ? '记下…' : noteId ? '更新今日一笔' : '记下今日一笔'}</Button>
        </form>
        {pastNotes.length > 0 && (
          <div className="violations">
            {pastNotes.map((item) => (
              <article key={item.id}>
                <span>{chinaDay(item.createdAt).slice(5)}</span>
                <div><b>{item.title}</b><p>{item.content}</p></div>
              </article>
            ))}
          </div>
        )}
      </Panel>
      {loading ? <StatusView state="loading" /> : error ? <StatusView state="error" message={error} onRetry={load} /> : !data ? <StatusView state="empty" /> : (
        <>
          <section className="review-scoreboard">
            <div className="score-lead"><span>累计净收益</span><strong className={data.totalProfit >= 0 ? 'gain' : 'loss'}>{money(data.totalProfit)}</strong><small>样本交易 {data.tradeCount ?? 0} 笔</small></div>
            <Metric label="交易胜率" value={`${Number(data.winRate || 0).toFixed(1)}%`} note="不求每次都对" />
            <Metric label="盈亏比" value={data.profitLossRatio ? `${data.profitLossRatio.toFixed(2)} : 1` : '—'} note="至少一笔盈利和亏损后计算" />
            <div className="review-motto"><i>复</i><span>日省其身<br /><small>知错即止</small></span></div>
          </section>

          <div className="review-grid">
            <Panel title="月度盈亏" eyebrow="MONTHLY PERFORMANCE" className="review-chart-panel">
              {data.monthly?.length ? <Chart option={monthlyOption} className="review-chart" ariaLabel="月度盈亏柱状图" /> : <StatusView state="empty" message="暂无月度统计" />}
            </Panel>
            <Panel title="纪律违例" eyebrow="VIOLATION LOG">
              {data.violations?.length ? <div className="violations">{data.violations.map((item, index) => (
                <article key={item.id || `${item.title}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><div><b>{item.title}</b><p>{item.detail || '已记录，等待复盘归因。'}</p></div>{item.date && <time>{item.date}</time>}</article>
              ))}</div> : <div className="clean-record"><span>✓</span><strong>本期无违例</strong><small>守住纪律，比抓住涨停更重要</small></div>}
            </Panel>
          </div>

          <Panel title="AI 复盘报告" eyebrow="AI COACH">
            <p className="check-intro">Grok 汇总胜率、盈亏比、违纪记录与最近交易的买入逻辑，指出重复出现的坏习惯。</p>
            <AICoach
              label="生成 AI 复盘报告"
              busyLabel="Grok 正在复盘…"
              hint="样本太少时 AI 会直说，不会过度解读"
              disabled={!data.tradeCount}
              run={() => api.aiReviewReport()}
            />
          </Panel>

          <Panel title="十条致命错误 · 今日自检" eyebrow="FATAL MISTAKES">
            <p className="check-intro">勾选今天发生过的错误。勾选不是羞耻，重复才是。</p>
            <div className="mistake-grid">{mistakes.slice(0, 10).map((item, index) => (
              <label key={item} className={checks.has(item) ? 'mistake checked' : 'mistake'}>
                <input type="checkbox" checked={checks.has(item)} onChange={() => toggleMistake(item)} />
                <span>{String(index + 1).padStart(2, '0')}</span><b>{item}</b><i>{checks.has(item) ? '今日发生' : '今日未犯'}</i>
              </label>
            ))}</div>
          </Panel>
        </>
      )}
    </div>
  )
}
