import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import { usePullDownRefresh, stopPullDownRefresh } from '@tarojs/taro'

import Panel from '../../components/Panel'
import Metric from '../../components/Metric'
import StatusView from '../../components/StatusView'
import { api, errorMessage } from '../../shared/api'
import { percent } from '../../shared/format'
import type { MarketMainline, MarketOverview, MarketPhase } from '../../shared/types'

import './index.scss'

const seasons: Array<{ key: MarketPhase; name: string; cn: string; action: string }> = [
  { key: 'spring', name: '春', cn: '复苏', action: '试探布局' },
  { key: 'summer', name: '夏', cn: '繁荣', action: '顺势持有' },
  { key: 'autumn', name: '秋', cn: '降温', action: '收缩仓位' },
  { key: 'winter', name: '冬', cn: '冰点', action: '耐心等待' },
]

export default function Dashboard() {
  const [data, setData] = useState<MarketOverview>()
  const [mainline, setMainline] = useState<MarketMainline>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [market, line] = await Promise.all([
        api.market(),
        api.mainline().catch(() => undefined),
      ])
      setData(market)
      setMainline(line)
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

  return (
    <ScrollView scrollY className='page dashboard'>
      <View className='page-header'>
        <Text className='page-header__eyebrow'>MARKET TEMPERATURE · 市场体感</Text>
        <Text className='page-header__title'>先观四时，再落一子</Text>
        <Text className='page-header__desc'>市场有温度，仓位有分寸。让趋势决定进退，不让情绪代替判断。</Text>
      </View>

      {loading ? (
        <StatusView state='loading' />
      ) : error ? (
        <StatusView state='error' message={error} onRetry={load} />
      ) : !data ? (
        <StatusView state='empty' />
      ) : (
        <View>
          {data.source === 'sample' && (
            <View className='source-notice'>
              <Text className='source-notice__title'>演示行情</Text>
              <Text className='source-notice__text'>实时数据源暂不可用，当前数字仅用于体验界面，不能作为交易依据。</Text>
            </View>
          )}

          <Panel className='temp-hero'>
            <View className='temp-hero__score'>
              <Text className='temp-hero__num'>{data.score}</Text>
              <Text className='temp-hero__unit'>市场温度</Text>
            </View>
            <View className='temp-hero__copy'>
              <Text className={`temp-hero__stamp phase-${data.phase}`}>
                {seasons.find((s) => s.key === data.phase)?.name || '观'}
              </Text>
              <Text className='temp-hero__phase'>
                {data.phaseLabel || seasons.find((s) => s.key === data.phase)?.cn || '观望期'}
              </Text>
              <Text className='temp-hero__summary'>{data.summary || '保持观察，等待趋势给出清晰方向。'}</Text>
            </View>
          </Panel>

          <Panel title='市场广度' eyebrow='BREADTH'>
            <View className='breadth-grid'>
              <Metric label='上涨家数' value={data.advance} tone='gain' />
              <Metric label='下跌家数' value={data.decline} tone='loss' />
              <Metric label='涨 / 跌停' value={`${data.limitUp} / ${data.limitDown}`} />
              <Metric label='炸板 / 量比' value={`${data.fried} / ${data.volumeRatio.toFixed(2)}`} />
            </View>
          </Panel>

          <View className='season-line'>
            {seasons.map((season, index) => (
              <View
                key={season.key}
                className={season.key === data.phase ? 'season-node season-node--active' : 'season-node'}
              >
                <Text className='season-node__idx'>0{index + 1}</Text>
                <Text className='season-node__name'>{season.name} · {season.cn}</Text>
                <Text className='season-node__action'>{season.action}</Text>
              </View>
            ))}
          </View>

          <Panel title='热点主线' eyebrow='MAINLINE · HOT SECTORS'>
            {mainline?.source === 'akshare' && mainline.sectors.length ? (
              <View>
                <View className='mainline-answer'>
                  <Text className='mainline-answer__label'>今日主线</Text>
                  <Text className='mainline-answer__value'>{mainline.mainSector || '待确认'}</Text>
                  <Text className='mainline-answer__hint'>
                    {mainline.activeSectors.length
                      ? `热点候选：${mainline.activeSectors.join(' · ')}`
                      : '涨停广度不足，暂不定义主线'}
                  </Text>
                </View>
                <View className='sector-list'>
                  {mainline.sectors.slice(0, 6).map((sector, index) => (
                    <View key={sector.name} className='sector-item'>
                      <View className='sector-item__head'>
                        <Text className='sector-item__rank'>{String(index + 1).padStart(2, '0')}</Text>
                        <Text className='sector-item__name'>{sector.name}</Text>
                        <Text className='sector-item__count'>{sector.limitUpCount} 涨停</Text>
                      </View>
                      <Text className='sector-item__detail'>
                        首板 {sector.firstBoardCount} · 二板+ {sector.secondPlusCount} · 高度 {sector.maxBoard} 板
                        {sector.leader ? ` · 领涨 ${sector.leader.name}` : ''}
                      </Text>
                    </View>
                  ))}
                </View>
                {mainline.ladders.length > 0 && (
                  <View className='ladder-box'>
                    <Text className='ladder-box__title'>连板梯队 · 龙头候选</Text>
                    {mainline.ladders.map((ladder) => (
                      <Text key={ladder.boardCount} className='ladder-box__row'>
                        {ladder.boardCount} 板：
                        {ladder.stocks.slice(0, 6).map((s) => s.name).join(' · ')}
                      </Text>
                    ))}
                  </View>
                )}
              </View>
            ) : (
              <StatusView state='empty' message={mainline?.fallbackReason || '今日涨停明细暂不可用'} />
            )}
          </Panel>

          <Panel title='核心指数' eyebrow='INDEX PULSE'>
            {data.indices.length ? (
              <View className='index-grid'>
                {data.indices.map((item) => (
                  <View key={item.code} className='index-card'>
                    <Text className='index-card__name'>{item.name}</Text>
                    <Text className='index-card__code'>{item.code}</Text>
                    <Text className='index-card__value'>
                      {item.value.toFixed(2)}
                    </Text>
                    <Text className={item.change >= 0 ? 'gain' : 'loss'}>{percent(item.change)}</Text>
                  </View>
                ))}
              </View>
            ) : (
              <StatusView state='empty' message='暂无指数行情' />
            )}
          </Panel>
        </View>
      )}
    </ScrollView>
  )
}
