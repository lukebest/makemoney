import { useCallback, useEffect, useState } from 'react'
import { View, Text, Button, ScrollView } from '@tarojs/components'
import Taro, { usePullDownRefresh, stopPullDownRefresh } from '@tarojs/taro'

import Panel from '../../components/Panel'
import StatusView from '../../components/StatusView'
import { api, errorMessage } from '../../shared/api'
import { amount, percent } from '../../shared/format'
import type { PreferredStocksData } from '../../shared/types'

import './index.scss'

export default function Preferred() {
  const [data, setData] = useState<PreferredStocksData>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await api.preferred())
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

  const openStock = (code: string) => {
    void Taro.navigateTo({ url: `/pages/stock/index?code=${code}` })
  }

  return (
    <ScrollView scrollY className='page preferred'>
      <View className='page-header'>
        <Text className='page-header__eyebrow'>SELECTION RADAR · 优选个股</Text>
        <Text className='page-header__title'>先缩小范围，再逐一求证</Text>
        <Text className='page-header__desc'>按热点主线、放量入场、短洗盘、价量重心和强势启动五项机器规则筛选；结果只是观察清单，不是买入建议。</Text>
      </View>

      {loading ? (
        <StatusView state='loading' message='正在预筛候选并逐只验证 K 线，首次加载可能需要十余秒' />
      ) : error ? (
        <StatusView state='error' message={error} onRetry={load} />
      ) : !data ? (
        <StatusView state='empty' />
      ) : (
        <View>
          {data.source === 'sample' && (
            <View className='source-notice'>
              <Text className='source-notice__title'>停止筛选</Text>
              <Text className='source-notice__text'>实时行情暂不可用。系统不会使用模拟数据生成优选名单。</Text>
            </View>
          )}

          <View className='screen-summary'>
            <View className='screen-summary__cell'>
              <Text className='screen-summary__label'>分析样本</Text>
              <Text className='screen-summary__value'>{data.analyzedCount}</Text>
            </View>
            <View className='screen-summary__cell'>
              <Text className='screen-summary__label'>进入清单</Text>
              <Text className='screen-summary__value'>{data.items.length}</Text>
            </View>
            <View className='screen-summary__cell'>
              <Text className='screen-summary__label'>评分口径</Text>
              <Text className='screen-summary__value'>5 × 20</Text>
            </View>
          </View>

          {!data.items.length ? (
            <StatusView state='empty' message='当前没有通过数据验证的候选，请稍后再试' />
          ) : (
            data.items.map((stock, index) => (
              <Panel key={stock.code} className='preferred-card'>
                <View className='preferred-card__head'>
                  <Text className='preferred-card__rank'>{String(index + 1).padStart(2, '0')}</Text>
                  <View className='preferred-card__id'>
                    <Text className='preferred-card__name'>{stock.name}</Text>
                    <Text className='preferred-card__code'>
                      {stock.code}
                      {stock.sector ? ` · ${stock.sector}${stock.inMainline ? ' · 主线' : ''}` : ''}
                    </Text>
                  </View>
                  <View className='preferred-card__score'>
                    <Text className='preferred-card__score-num'>{stock.score}</Text>
                    <Text className='preferred-card__setup'>{stock.setup}</Text>
                  </View>
                </View>

                <View className='preferred-card__price'>
                  <Text className='preferred-card__last'>{stock.price.toFixed(2)}</Text>
                  <Text className={stock.change >= 0 ? 'gain' : 'loss'}>{percent(stock.change)}</Text>
                  <Text className='muted'>成交额 {amount(stock.amount)}</Text>
                </View>

                <View className='preferred-card__checks'>
                  {stock.checks.map((check) => (
                    <View key={check.key} className='check-row'>
                      <Text className={`check-row__mark check-row__mark--${check.status}`}>
                        {check.status === 'passed' ? '✓' : check.status === 'manual' ? '?' : '×'}
                      </Text>
                      <Text className='check-row__label'>{check.label}</Text>
                    </View>
                  ))}
                </View>

                <View className='preferred-card__foot'>
                  <Text className='muted'>
                    洗盘 {stock.washoutDays ?? '—'} 日 · 止损参考 {stock.stopLoss?.toFixed(2) ?? '—'}
                  </Text>
                  <Button className='pill-btn pill-btn--ghost' size='mini' onClick={() => openStock(stock.code)}>
                    打开诊断
                  </Button>
                </View>
              </Panel>
            ))
          )}
        </View>
      )}
    </ScrollView>
  )
}
