import { useCallback, useEffect, useState } from 'react'
import { View, Text, Button, ScrollView } from '@tarojs/components'
import Taro from '@tarojs/taro'

import Panel from '../../components/Panel'
import StatusView from '../../components/StatusView'
import { api, errorMessage } from '../../shared/api'
import { ensureLogin } from '../../shared/auth'
import { yuanFromFen } from '../../shared/format'
import type { CreditBalance, CreditSkusData } from '../../shared/types'

import './index.scss'

export default function Credits() {
  const [balance, setBalance] = useState<CreditBalance>()
  const [skus, setSkus] = useState<CreditSkusData>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busySku, setBusySku] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      await ensureLogin()
      const [creditData, skuData] = await Promise.all([api.credits(), api.creditSkus()])
      setBalance(creditData)
      setSkus(skuData)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function purchase(sku: string) {
    if (!skus?.mockPayAllowed) {
      await Taro.showModal({
        title: '暂不可支付',
        content: '当前环境未开启支付（生产环境默认熔断，或未配置真实微信支付）。',
        showCancel: false,
      })
      return
    }
    setBusySku(sku)
    setError('')
    try {
      const { order } = await api.createOrder(sku)
      const result = await api.mockPay(order.id)
      setBalance(result.credits)
      await Taro.showToast({ title: result.alreadyPaid ? '订单已支付' : '充值成功', icon: 'success' })
      const fresh = await api.credits()
      setBalance(fresh)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusySku('')
    }
  }

  return (
    <ScrollView scrollY className='page credits'>
      <View className='page-header'>
        <Text className='page-header__eyebrow'>AI CREDITS · AI 点数</Text>
        <Text className='page-header__title'>为清醒的建议付费</Text>
        <Text className='page-header__desc'>每次 AI 教练解读消耗点数，点数用于覆盖模型成本。</Text>
      </View>

      {loading ? (
        <StatusView state='loading' />
      ) : error ? (
        <StatusView state='error' message={error} onRetry={load} />
      ) : (
        <View>
          <Panel className='balance-card'>
            <Text className='balance-card__label'>当前点数余额</Text>
            <Text className='balance-card__value'>{balance?.balance ?? 0}</Text>
            <Text className='muted'>每次解读消耗 {skus?.aiCreditCost ?? balance?.aiCreditCost ?? 1} 点</Text>
          </Panel>

          {!skus?.mockPayAllowed && (
            <View className='source-notice'>
              <Text className='source-notice__title'>支付未开启</Text>
              <Text className='source-notice__text'>
                当前支付方式（{skus?.provider || 'mock'}）不可下单。生产环境默认熔断模拟支付，请配置真实微信支付或开启 ALLOW_MOCK_PAYMENTS。
              </Text>
            </View>
          )}

          <Panel title='点数包' eyebrow='CREDIT PACKS'>
            {skus?.items.map((sku) => (
              <View key={sku.sku} className={`sku ${sku.popular ? 'sku--popular' : ''}`}>
                <View className='sku__info'>
                  <Text className='sku__title'>
                    {sku.title}{sku.popular ? ' · 推荐' : ''}
                  </Text>
                  <Text className='sku__desc'>{sku.description || `${sku.credits} 次 AI 解读`}</Text>
                </View>
                <View className='sku__right'>
                  <Text className='sku__price'>{yuanFromFen(sku.amountFen)}</Text>
                  <Text className='sku__credits'>{sku.credits} 点</Text>
                </View>
                <Button
                  className='pill-btn sku__buy'
                  size='mini'
                  loading={busySku === sku.sku}
                  disabled={!skus?.mockPayAllowed || Boolean(busySku)}
                  onClick={() => void purchase(sku.sku)}
                >
                  {skus?.mockPayAllowed ? '购买' : '不可购买'}
                </Button>
              </View>
            ))}
          </Panel>

          <Panel title='点数流水' eyebrow='LEDGER'>
            {balance?.ledger && balance.ledger.length ? (
              balance.ledger.map((entry) => (
                <View key={entry.id} className='ledger-row'>
                  <View className='ledger-row__body'>
                    <Text className='ledger-row__reason'>{entry.reason || (entry.amount >= 0 ? '充值' : '消耗')}</Text>
                    <Text className='ledger-row__time'>{(entry.createdAt || '').slice(0, 16).replace('T', ' ')}</Text>
                  </View>
                  <Text className={`ledger-row__amount ${entry.amount >= 0 ? 'gain' : 'loss'}`}>
                    {entry.amount >= 0 ? '+' : ''}{entry.amount}
                  </Text>
                </View>
              ))
            ) : (
              <StatusView state='empty' message='暂无点数流水' />
            )}
          </Panel>

          <Text className='disclaimer'>
            点数仅用于兑换 AI 解读服务，不可提现、不可转让。AI 输出为研究性质的观点，不构成投资建议，不保证收益。请理性交易，风险自担。
          </Text>
        </View>
      )}
    </ScrollView>
  )
}
