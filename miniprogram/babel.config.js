// babel-preset-taro is a wrapper that configures presets for the chosen framework.
// https://docs.taro.zone/docs/babel-config
module.exports = {
  presets: [
    ['taro', {
      framework: 'react',
      ts: true,
      compiler: 'webpack5'
    }]
  ]
}
