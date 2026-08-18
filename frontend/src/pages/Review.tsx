import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import type { EChartsOption } from 'echarts'
import { Link } from 'react-router-dom'
import { afterCloseSession, api, beforeOpen, errorMessage, sessionLooksStuck, tapeClosed } from '../api'
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

const journalDay = (item: JournalEntry) => {
  const match = item.title.match(/^(\d{4}-\d{2}-\d{2})/)
  return match ? match[1] : chinaDay(item.createdAt)
}

const defaultMistakes = [
  '把投资当业余爱好，却期待专业收益', '三分钟草率审查一只股票', '野心很大，耐性不足',
  '假装勤奋，缺少真正思考', '只买生，不买熟', '买时过度自信，买后过度恐慌',
  '机械套用技术止损', '追求确定性和精准买点', '知识碎片化', '靠意念炒股',
]

const chinaToday = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })

const reviewDay = (briefing?: TodayBriefing) =>
  tapeClosed(briefing?.session.code) ? briefing?.session.asOfDate || chinaToday() : chinaToday()

function loadChecks(day: string) {
  try {
    const raw = JSON.parse(localStorage.getItem('fatal-mistake-checks') || '[]')
    if (raw && !Array.isArray(raw) && raw.date === day && Array.isArray(raw.items)) {
      return new Set<string>(raw.items)
    }
  } catch { /* start a fresh day */ }
  return new Set<string>()
}

export function Review() {
  const [data, setData] = useState<ReviewData>()
  const [briefing, setBriefing] = useState<TodayBriefing>()
  const [checks, setChecks] = useState<Set<string>>(() => loadChecks(chinaToday()))
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
    void Promise.all([
      api.today(true).catch(() => undefined),
      api.journals().catch(() => undefined),
    ]).then(([brief, items]) => {
      if (brief) setBriefing(brief)
      if (!items) return
      setJournals(items)
      const current = (brief?.session.asOfDate
        && items.find((item) => journalDay(item) === brief.session.asOfDate))
        || items.find((item) => journalDay(item) === chinaToday())
      if (current) {
        setNoteId(current.id)
        setNote(current.content)
      }
    })
    try { setData(await api.review()) } catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void api.today(true).then(setBriefing).catch(() => undefined)
    }, 4000)
    const tick = window.setInterval(() => {
      if (!sessionLooksStuck(briefing?.session.code)) return
      void api.today(true).then(setBriefing).catch(() => undefined)
    }, 15_000)
    return () => {
      window.clearTimeout(timer)
      window.clearInterval(tick)
    }
  }, [briefing?.session.code])
  const scanJob = briefing?.closeScreen.job
  useEffect(() => {
    if (scanJob?.status !== 'running') return
    const timer = window.setInterval(() => {
      void api.today(true).then(setBriefing).catch(() => undefined)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [scanJob?.status])
  const startTonightScan = () => {
    void api.startCloseScreen()
      .then(() => api.today(true).then(setBriefing))
      .catch(() => undefined)
  }
  useEffect(() => {
    if (!briefing) return
    setChecks(loadChecks(reviewDay(briefing)))
  }, [briefing?.session.asOfDate, briefing?.session.code])

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
    localStorage.setItem('fatal-mistake-checks', JSON.stringify({ date: reviewDay(briefing), items: [...next] }))
  }

  const mistakes = data?.fatalMistakes?.length ? data.fatalMistakes : defaultMistakes
  const todayStamp = reviewDay(briefing)
  const pastNotes = journals.filter((item) => item.id !== noteId).slice(0, 3)
  const journalFacts = briefing
    ? [
      briefing.stops.length
        ? `止损触发：${briefing.stops.map((item) => item.name).join('、')}`
        : '',
      briefing.discipline?.exits?.length
        ? `今日卖出：${briefing.discipline.exits.map((item) => (
          item.note ? `${item.name}（${item.note}）` : item.name
        )).join('、')}`
        : '',
      briefing.discipline?.offList.length
        ? `清单外买入：${briefing.discipline.offList.map((item) => item.name).join('、')}`
        : '',
      briefing.closeScreen.items.length
        ? `${briefing.closeScreen.needsRun ? '上次精选' : afterCloseSession(briefing.session.code) ? '今晚精选' : '昨夜精选'}：${briefing.closeScreen.items.slice(0, 5).map((item) => (
          `${item.name}${item.liveChange != null ? ` ${percent(item.liveChange)}` : ''}`
        )).join(' · ')}`
        : '',
    ].filter(Boolean)
    : []

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
        createdAt: `${todayStamp}T16:00:00+08:00`,
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
      {briefing && (briefing.closeScreen.needsRun || briefing.closeScreen.items.length || briefing.discipline?.buyCount || briefing.discipline?.exits?.length || briefing.stops.length) ? (
        <section className="daily-brief" aria-label="精选回顾">
          <div>
            <span>{briefing.closeScreen.needsRun ? '上次清单' : afterCloseSession(briefing.session.code) ? '明日观察' : '今日观察'} · {briefing.closeScreen.asOfDate || '尚未筛选'}</span>
            <strong>
              {briefing.closeScreen.needsRun
                ? (beforeOpen(briefing.session.code)
                  ? '开盘前先完成昨夜精选，旧清单不能当今日计划'
                  : afterCloseSession(briefing.session.code)
                    ? '收盘已过，先运行今晚精选'
                    : '今日精选尚未生成，旧清单不能当计划')
                : (afterCloseSession(briefing.session.code)
                  ? '今晚精选，下一交易日只做清单内的票'
                  : '昨夜精选，今日只做清单内的票')}
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
            {briefing.discipline?.exits?.length ? (
              <li>
                <b>卖出</b>
                {briefing.discipline.exits.slice(0, 3).map((item) => (
                  <span key={`${item.code}-${item.note}`}>{item.name}{item.note ? ` · ${item.note}` : ''}</span>
                ))}
              </li>
            ) : null}
            {briefing.closeScreen.job?.status === 'running' ? (
              <li>
                <b>扫描</b>
                <Link to="/preferred">
                  已验 {briefing.closeScreen.job.checked ?? 0}/{briefing.closeScreen.job.total ?? '…'}
                  {briefing.closeScreen.job.matches != null ? ` · 通过 ${briefing.closeScreen.job.matches}` : ''}
                </Link>
              </li>
            ) : briefing.closeScreen.needsRun && (
              <li>
                <b>{afterCloseSession(briefing.session.code) ? '今晚' : '精选'}</b>
                <button type="button" className="brief-action" onClick={startTonightScan}>
                  {beforeOpen(briefing.session.code)
                    ? '开盘前，先完成昨夜精选'
                    : afterCloseSession(briefing.session.code)
                      ? '收盘已过，运行今晚精选'
                      : '今日精选尚未生成，旧清单不能当计划'}
                </button>
                <Link to="/preferred">看清单</Link>
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
                <li><Link to="/preferred">今晚五项全过 0 只</Link></li>
              )}
          </ol>
        </section>
      ) : null}
      <Panel title="十条致命错误 · 今日自检" eyebrow="FATAL MISTAKES">
        <p className="check-intro">先勾选今晚发生过的错误，再写下面临的那一笔。勾选不是羞耻，重复才是。</p>
        <div className="mistake-grid">{mistakes.slice(0, 10).map((item, index) => (
          <label key={item} className={checks.has(item) ? 'mistake checked' : 'mistake'}>
            <input type="checkbox" checked={checks.has(item)} onChange={() => toggleMistake(item)} />
            <span>{String(index + 1).padStart(2, '0')}</span><b>{item}</b><i>{checks.has(item) ? '今日发生' : '今日未犯'}</i>
          </label>
        ))}</div>
      </Panel>
      <Panel title="今日一笔" eyebrow="DAILY NOTE">
        <p className="check-intro">收盘后用几句话写下过程，不写盈亏故事。有清单外买入时，先写为什么破例。</p>
        {journalFacts.length > 0 && (
          <ul className="journal-facts">
            {journalFacts.map((fact) => <li key={fact}>{fact}</li>)}
          </ul>
        )}
        {checks.size > 0 && (
          <p className="check-intro">已勾选 {checks.size} 条今晚发生的错误，写进这一笔里。</p>
        )}
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
                <span>{journalDay(item).slice(5)}</span>
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
        </>
      )}
    </div>
  )
}
