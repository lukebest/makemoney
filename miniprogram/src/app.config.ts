import { defineAppConfig } from '@tarojs/taro'

export default defineAppConfig({
  pages: [
    'pages/dashboard/index',
    'pages/preferred/index',
    'pages/positions/index',
    'pages/trades/index',
    'pages/review/index',
    'pages/stock/index',
    'pages/credits/index'
  ],
  window: {
    backgroundTextStyle: 'light',
    backgroundColor: '#0c0d0b',
    navigationBarBackgroundColor: '#11130f',
    navigationBarTitleText: '知止',
    navigationBarTextStyle: 'white'
  },
  tabBar: {
    color: '#8d887c',
    selectedColor: '#b2975b',
    backgroundColor: '#11130f',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'pages/dashboard/index',
        text: '温度'
      },
      {
        pagePath: 'pages/preferred/index',
        text: '优选'
      },
      {
        pagePath: 'pages/positions/index',
        text: '仓位'
      },
      {
        pagePath: 'pages/trades/index',
        text: '交易'
      },
      {
        pagePath: 'pages/review/index',
        text: '复盘'
      }
    ]
  }
})
