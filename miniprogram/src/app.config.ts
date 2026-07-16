export default defineAppConfig({
  pages: [
    'pages/dashboard/index',
    'pages/preferred/index',
    'pages/positions/index',
    'pages/trades/index',
    'pages/review/index',
    'pages/stock/index',
    'pages/credits/index',
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#11130f',
    navigationBarTitleText: '知止',
    navigationBarTextStyle: 'white',
    backgroundColor: '#0c0d0b',
  },
  tabBar: {
    color: '#8a8578',
    selectedColor: '#b2975b',
    backgroundColor: '#11130f',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'pages/dashboard/index',
        text: '温度',
        iconPath: 'assets/tab/dashboard.png',
        selectedIconPath: 'assets/tab/dashboard-active.png',
      },
      {
        pagePath: 'pages/preferred/index',
        text: '优选',
        iconPath: 'assets/tab/preferred.png',
        selectedIconPath: 'assets/tab/preferred-active.png',
      },
      {
        pagePath: 'pages/positions/index',
        text: '仓位',
        iconPath: 'assets/tab/positions.png',
        selectedIconPath: 'assets/tab/positions-active.png',
      },
      {
        pagePath: 'pages/trades/index',
        text: '交易',
        iconPath: 'assets/tab/trades.png',
        selectedIconPath: 'assets/tab/trades-active.png',
      },
      {
        pagePath: 'pages/review/index',
        text: '复盘',
        iconPath: 'assets/tab/review.png',
        selectedIconPath: 'assets/tab/review-active.png',
      },
    ],
  },
})
