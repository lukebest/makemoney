import type { UserConfigExport } from '@tarojs/cli'

export default {
  mini: {},
  h5: {
    /**
     * WebpackChain 插件配置
     * @docs https://github.com/neutrinojs/webpack-chain
     */
    // webpackChain (chain) {
    //   /**
    //    * 如果 h5 端首次加载时间过长，可以使用 SplitChunksPlugin 进行代码分割
    //    * @docs https://webpack.js.org/plugins/split-chunks-plugin/
    //    */
    //   chain.optimization.splitChunks({
    //     chunks: 'all',
    //     maxInitialRequests: Infinity,
    //     minSize: 0,
    //     cacheGroups: {
    //       common: {
    //         name: 'common',
    //         minChunks: 2,
    //         priority: 1
    //       },
    //       vendors: {
    //         name: 'vendors',
    //         minChunks: 2,
    //         test: /[\\/]node_modules[\\/]/,
    //         priority: 10
    //       }
    //     }
    //   })
    // }
  }
} satisfies UserConfigExport<'webpack5'>
