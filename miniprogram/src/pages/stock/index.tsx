import { View, Text } from '@tarojs/components'
import { useRouter } from '@tarojs/taro'
import './index.scss'

export default function Stock() {
  const router = useRouter()
  const code = router.params.code ?? ''

  return (
    <View className='stock-page'>
      <Text className='stock-page__title'>个股详情</Text>
      <Text className='stock-page__code'>{code ? `股票代码：${code}` : '未提供股票代码'}</Text>
      <Text className='stock-page__hint'>页面骨架，内容待补充</Text>
    </View>
  )
}
