import { View, Text, Button } from '@tarojs/components'

interface StatusViewProps {
  state: 'loading' | 'error' | 'empty'
  message?: string
  onRetry?: () => void
}

export default function StatusView({ state, message, onRetry }: StatusViewProps) {
  const copy = {
    loading: ['正在接入行情…', '数据列阵中'],
    error: ['数据暂不可用', message || '服务连接失败'],
    empty: ['暂无记录', message || '这里还没有数据'],
  }[state]
  const mark = state === 'loading' ? '◌' : state === 'error' ? '!' : '空'
  return (
    <View className={`status-view status-view--${state}`}>
      <Text className='status-view__mark'>{mark}</Text>
      <Text className='status-view__title'>{copy[0]}</Text>
      <Text className='status-view__hint'>{copy[1]}</Text>
      {onRetry && state === 'error' && (
        <Button className='status-view__retry' size='mini' onClick={onRetry}>
          重新连接
        </Button>
      )}
    </View>
  )
}
