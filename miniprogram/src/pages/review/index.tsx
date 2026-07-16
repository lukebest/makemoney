import { useCallback, useEffect, useState } from 'react'
import { View, Text, Button, ScrollView } from '@tarojs/components'
import Taro, { usePullDownRefresh, stopPullDownRefresh } from '@tarojs/taro'

import Panel from '../../components/Panel'
import Metric from '../../components/Metric'
import StatusView from '../../components/StatusView'
import { api, ApiError, errorMessage } from '../../shared/api'
import { ensureLogin } from '../../shared/auth'
import { money } from '../../shared/format'
import type { AIResult, ReviewData } from '../../shared/types'

import './index.scss'

export default function Review() {
  const [data, setData] = useState<ReviewData>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [ai, setAi] = useState<AIResult>()
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await api.review())
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

  async function runReport() {
    setAiBusy(true)
    setAiError('')
    try {
      await ensureLogin()
      setAi(await api.aiReviewReport())
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

  const maxAbs = data?.monthly.reduce((m, item) => Math.max(m, Math.abs(item.profit)), 1) || 1

  return (
    <ScrollView scrollY className='page review'>
      <View className='page-header'>
        <Text className='page-header__eyebrow'>CLOSING REVIEW · 收盘复盘</Text>
        <Text className='page-header__title'>把结果交给统计，把错误留在今天</Text>
        <Text className='page-header__desc'>复盘不是审判盈亏，而是检查过程。</Text>
      </View>

      {loading ? (
        <StatusView state='loading' />
      ) : error ? (
        <StatusView state='error' message={error} onRetry={load} />
      ) : !data ? (
        <StatusView state='empty' />
      ) : (
        <View>
          <Panel title='累计成绩' eyebrow='SCOREBOARD'>
            <View className='score-lead'>
              <Text className='score-lead__label'>累计净收益</Text>
              <Text className={`score-lead__value ${data.totalProfit >= 0 ? 'gain' : 'loss'}`}>{money(data.totalProfit)}</Text>
              <Text className='muted'>样本交易 {data.tradeCount} 笔</Text>
            </View>
            <View className='metric-row'>
              <Metric label='交易胜率' value={`${data.winRate.toFixed(1)}%`} note='不求每次都对' />
              <Metric label='盈亏比' value={data.profitLossRatio ? `${data.profitLossRatio.toFixed(2)} : 1` : '—'} note='盈亏各一笔后计算' />
            </View>
          </Panel>

          <Panel title='月度盈亏' eyebrow='MONTHLY PERFORMANCE'>
            {data.monthly.length ? (
              data.monthly.map((item) => {
                const width = (Math.abs(item.profit) / maxAbs) * 100
                return (
                  <View key={item.month} className='month-row'>
                    <Text className='month-row__label'>{item.month}</Text>
                    <View className='month-row__track'>
                      <View
                        className={`month-row__bar ${item.profit >= 0 ? 'month-row__bar--gain' : 'month-row__bar--loss'}`}
                        style={`width:${width}%`}
                      />
                    </View>
                    <Text className={`month-row__value ${item.profit >= 0 ? 'gain' : 'loss'}`}>{money(item.profit)}</Text>
                  </View>
                )
              })
            ) : (
              <StatusView state='empty' message='暂无月度统计' />
            )}
          </Panel>

          <Panel title='纪律违例' eyebrow='VIOLATION LOG'>
            {data.violations.length ? (
              data.violations.map((item, index) => (
                <View key={item.id || `${item.title}-${index}`} className='violation'>
                  <Text className='violation__idx'>{String(index + 1).padStart(2, '0')}</Text>
                  <View className='violation__body'>
                    <Text className='violation__title'>{item.title}</Text>
                    <Text className='violation__detail'>{item.detail || '已记录，等待复盘归因。'}</Text>
                  </View>
                </View>
              ))
            ) : (
              <View className='clean-record'>
                <Text className='clean-record__mark'>✓</Text>
                <Text className='clean-record__title'>本期无违例</Text>
                <Text className='muted'>守住纪律，比抓住涨停更重要</Text>
              </View>
            )}
          </Panel>

          <Panel title='AI 复盘报告' eyebrow='AI COACH'>
            <Text className='muted'>Grok 汇总胜率、盈亏比与最近交易逻辑，指出重复出现的坏习惯。将消耗 AI 点数。</Text>
            <Button className='pill-btn' loading={aiBusy} disabled={!data.tradeCount} onClick={() => void runReport()}>
              {aiBusy ? 'Grok 正在复盘…' : '生成 AI 复盘报告'}
            </Button>
            {aiError ? <Text className='loss ai-error'>{aiError}</Text> : null}
            {ai ? (
              <View className='ai-result'>
                {ai.hardWarnings.map((w) => (
                  <Text key={w} className='ai-result__warning'>⚠ {w}</Text>
                ))}
                <Text className='ai-result__text'>{ai.text}</Text>
                <Text className='muted'>
                  {ai.model}{ai.creditsBalance != null ? ` · 余额 ${ai.creditsBalance} 点` : ''}
                </Text>
              </View>
            ) : null}
          </Panel>
        </View>
      )}
    </ScrollView>
  )
}
