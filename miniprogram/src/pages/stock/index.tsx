import { useCallback, useEffect, useMemo, useState } from 'react'
import { View, Text, Input, Button, ScrollView } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import Panel from '../../components/Panel'
import Metric from '../../components/Metric'
import StatusView from '../../components/StatusView'
import { api, ApiError, errorMessage } from '../../shared/api'
import { ensureLogin } from '../../shared/auth'
import { percent } from '../../shared/format'
import type { AIResult, StockAnalysis } from '../../shared/types'

import './index.scss'

const CODE_RE = /^(?:\d{5}|\d{6})$/

export default function Stock() {
  const router = useRouter()
  const [code, setCode] = useState('')
  const [data, setData] = useState<StockAnalysis>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [ai, setAi] = useState<AIResult>()
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState('')

  const analyze = useCallback(async (value: string) => {
    const normalized = value.trim().toUpperCase().replace(/^(SH|SZ|HK)/, '')
    if (!CODE_RE.test(normalized)) {
      setError('请输入 6 位 A 股或 5 位港股代码，例如 600519、00700')
      return
    }
    setLoading(true)
    setError('')
    setAi(undefined)
    setAiError('')
    try {
      setData(await api.stock(normalized))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const initial = router.params?.code
    if (initial) {
      setCode(initial)
      void analyze(initial)
    }
  }, [router.params?.code, analyze])

  const bars = useMemo(() => (data?.klines || []).slice(-20), [data])
  const barRange = useMemo(() => {
    if (!bars.length) return { min: 0, max: 1 }
    const closes = bars.map((b) => b.close)
    return { min: Math.min(...closes), max: Math.max(...closes) }
  }, [bars])

  async function runAI() {
    if (!data) return
    setAiBusy(true)
    setAiError('')
    try {
      await ensureLogin()
      setAi(await api.aiInterpret(data.code))
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        void Taro.navigateTo({ url: '/pages/credits/index' })
        return
      }
      setAiError(errorMessage(e))
    } finally {
      setAiBusy(false)
    }
  }

  return (
    <ScrollView scrollY className='page stock'>
      <View className='page-header'>
        <Text className='page-header__eyebrow'>STOCK DIAGNOSIS · 个股诊断</Text>
        <Text className='page-header__title'>不预测，只确认</Text>
        <Text className='page-header__desc'>观察价格、均线与成交量是否说着同一种语言。</Text>
      </View>

      <View className='stock-search'>
        <Input
          className='stock-search__input'
          value={code}
          type='number'
          placeholder='A股 600519 / 港股 00700'
          onInput={(e) => setCode(e.detail.value)}
        />
        <Button className='pill-btn' size='mini' loading={loading} onClick={() => void analyze(code)}>
          诊断
        </Button>
      </View>

      {loading ? (
        <StatusView state='loading' />
      ) : error ? (
        <StatusView state='error' message={error} />
      ) : !data ? (
        <StatusView state='empty' message='键入股票代码，让数据先开口' />
      ) : (
        <View>
          {data.source === 'sample' && (
            <View className='source-notice'>
              <Text className='source-notice__title'>演示行情</Text>
              <Text className='source-notice__text'>K 线为模拟数据，不能作为交易依据，AI 解读已禁用。</Text>
            </View>
          )}

          <Panel className='stock-ticker'>
            <View className='stock-ticker__id'>
              <Text className='stock-ticker__code'>{data.code}{data.market === 'HK' ? ' · 港股' : ''}</Text>
              <Text className='stock-ticker__name'>{data.name}</Text>
            </View>
            <View className='stock-ticker__metrics'>
              <Metric label={`现价 · ${data.currency || 'CNY'}`} value={data.price.toFixed(2)} />
              <Metric label='涨跌幅' value={percent(data.change)} tone={data.change >= 0 ? 'gain' : 'loss'} />
              <Metric label='趋势' value={data.trend} note={data.score != null ? `强度 ${data.score}` : undefined} />
            </View>
          </Panel>

          <Panel title='近 20 日收盘' eyebrow='PRICE TREND'>
            {bars.length ? (
              <View className='kline-bars'>
                {bars.map((bar, i) => {
                  const span = barRange.max - barRange.min || 1
                  const h = 20 + ((bar.close - barRange.min) / span) * 80
                  const prev = i > 0 ? bars[i - 1].close : bar.open
                  const up = bar.close >= prev
                  return (
                    <View key={bar.date} className='kline-bars__col'>
                      <View
                        className={`kline-bars__bar ${up ? 'kline-bars__bar--up' : 'kline-bars__bar--down'}`}
                        style={`height:${h}%`}
                      />
                    </View>
                  )
                })}
              </View>
            ) : (
              <StatusView state='empty' message='暂无K线数据' />
            )}
            <View className='kline-legend'>
              <Text className='muted'>最低 {barRange.min.toFixed(2)}</Text>
              <Text className='muted'>最高 {barRange.max.toFixed(2)}</Text>
            </View>
          </Panel>

          {data.structure && (
            <Panel title='主力阶段与承接' eyebrow='STRUCTURE'>
              <View className='structure-card'>
                <Text className='structure-card__label'>量价阶段</Text>
                <Text className='structure-card__value'>{data.structure.label}</Text>
                <Text className='structure-card__summary'>{data.structure.summary}</Text>
              </View>
              <View className='structure-card'>
                <Text className='structure-card__label'>买卖承接</Text>
                <Text className='structure-card__value'>{data.structure.acceptance.label}</Text>
                <Text className='structure-card__summary'>{data.structure.acceptance.summary}</Text>
              </View>
              <Text className='muted structure-disclaimer'>
                “建仓、洗盘、拉升、出货”均为量价规则的疑似判定，不代表已识别真实主力意图。
              </Text>
            </Panel>
          )}

          <Panel title='趋势结论' eyebrow='VERDICT'>
            <Text className='verdict'>{data.summary || data.trend || '趋势信号尚不充分，继续观察。'}</Text>
            {(data.support || data.resistance) ? (
              <Text className='muted'>
                近20日支撑 {(data.support || 0).toFixed(2)} · 压力 {(data.resistance || 0).toFixed(2)}
              </Text>
            ) : null}
          </Panel>

          <Panel title='入场检查' eyebrow='DISCIPLINE CHECK'>
            {data.checks.length ? (
              data.checks.map((item, i) => (
                <View key={`${item.label}-${i}`} className='check-line'>
                  <Text className={`check-line__mark ${item.passed ? 'check-line__mark--pass' : 'check-line__mark--fail'}`}>
                    {item.passed ? '✓' : '×'}
                  </Text>
                  <View className='check-line__body'>
                    <Text className='check-line__label'>{item.label}</Text>
                    {item.detail ? <Text className='check-line__detail'>{item.detail}</Text> : null}
                  </View>
                </View>
              ))
            ) : (
              <StatusView state='empty' message='暂无检查项' />
            )}
          </Panel>

          {data.source !== 'sample' && (
            <Panel title='AI 教练解读' eyebrow='AI COACH'>
              <Text className='muted'>基于上方机器信号生成，不构成投资建议。首次调用将消耗 AI 点数。</Text>
              <Button className='pill-btn' loading={aiBusy} onClick={() => void runAI()}>
                {aiBusy ? 'Grok 正在解读…' : 'AI 解读这些信号'}
              </Button>
              {aiError ? <Text className='loss ai-error'>{aiError}</Text> : null}
              {ai ? (
                <View className='ai-result'>
                  {ai.hardWarnings.map((w) => (
                    <Text key={w} className='ai-result__warning'>⚠ {w}</Text>
                  ))}
                  <Text className='ai-result__text'>{ai.text}</Text>
                  <Text className='muted'>
                    {ai.model}{ai.creditsCharged != null ? ` · 消耗 ${ai.creditsCharged} 点` : ''}
                    {ai.creditsBalance != null ? ` · 余额 ${ai.creditsBalance} 点` : ''}
                  </Text>
                </View>
              ) : null}
            </Panel>
          )}
        </View>
      )}
    </ScrollView>
  )
}
