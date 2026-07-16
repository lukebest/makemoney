# A 股散户纪律系统

把《炒股挣钱讲座》中的“顺势而为、仓位管理、止损纪律、买入三问”
落成可执行、可复盘的 Web / 微信小程序工具。系统用于管理交易纪律，不构成投资建议，
也不承诺收益。

## 功能

- 市场温度：展示主要指数，并按真实涨停/炸板/跌停家数与沪指量能比判断春播、夏长、秋收、冬藏
- 热点主线：按行业首板广度识别热点，按二板以上高度展示龙头候选和连板梯队
- 优选个股：热点板块优先进入候选池，用主线、量能、洗盘、价量重心与启动信号生成观察清单
- 个股分析：展示日 K、均线、缠论结构，以及疑似建仓/洗盘/拉升/出货和买卖承接
- 仓位管理：334 仓位目标、持仓盈亏、止损与破 60 日线提醒
- 交易台账：买入前强制回答“逻辑、资金、空间”并设置止损
- 趋势闸门：买入前自动校验上升趋势和疑似出货，非主升结构必须二次确认
- 复盘统计：胜率、盈亏比、月度盈亏、违纪次数与常见错误
- AI 教练（可选）：基于 Cursor SDK（Grok 4.5 high fast）解读个股信号、审查买入三问、生成复盘报告
- 微信小程序：独立 Taro 客户端；微信登录后 AI 按次扣点，开发环境支持模拟充值

## 技术栈

- Web 前端：React、TypeScript、Vite、Apache ECharts（`frontend/`）
- 微信小程序：Taro 4 + React + TypeScript（`miniprogram/`）
- 后端：FastAPI、SQLite、akshare、可选 Cursor SDK

## 本地运行

### 1. 后端

```bash
cp .env.example .env   # 按需填写
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

接口文档位于 <http://localhost:8000/docs>。

### 2. Web 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。开发服务器会将 `/api` 代理到后端。

### 3. 微信小程序

```bash
cd miniprogram
npm install
# 可选：指定后端地址（真机调试需局域网 HTTPS 或关闭域名校验）
export TARO_APP_API_BASE=http://127.0.0.1:8000/api
npm run dev:weapp
```

用微信开发者工具导入 `miniprogram/` 目录（`miniprogramRoot` 指向 `dist/`，见 `project.config.json`）。

本地无 AppID 时：

1. `project.config.json` 使用占位 `touristappid`
2. 开发者工具勾选「不校验合法域名」
3. 后端默认 `APP_ENV=development`，可用 `POST /api/auth/dev` 或 `code=mock:xxx` 登录
4. `PAYMENT_PROVIDER=mock` 且 `ALLOW_MOCK_PAYMENTS=1` 时可在点数页模拟支付

## 验证

```bash
source .venv/bin/activate
pytest

cd frontend && npm run build
cd ../miniprogram && npm run build:weapp
```

## 环境变量

见 [`.env.example`](.env.example)：

| 变量 | 说明 |
|------|------|
| `WECHAT_APP_ID` / `WECHAT_APP_SECRET` | 正式微信登录；生产缺失时拒绝模拟登录 |
| `APP_ENV` | `development` / `production` |
| `PAYMENT_PROVIDER` | `mock` 或 `wechat` |
| `ALLOW_MOCK_PAYMENTS` | 生产默认应关闭；禁止伪造支付成功 |
| `CURSOR_API_KEY` | AI 教练；未设置时 AI 返回 503 |
| `AI_CREDIT_COST` | 每次 AI 调用扣点数（默认 1） |
| `TARO_APP_API_BASE` | 小程序编译期 API 根路径 |

## 数据与多用户说明

实时行情通过 akshare 获取。上游网络不可用时，界面会明确显示降级状态并使用演示数据。
持仓与台账保存在 SQLite；后端按用户隔离。Web 未登录时落到 `local-web` 用户（兼容原单机用法）；
小程序通过微信 / 开发登录获得独立账户。

港股价格以港币记录，仓位和盈亏按中行港币折算价换算为人民币汇总。

缠论结构（分型、笔、中枢、类三买）由 `backend/chan.py` 的纯函数计算，
可用 `PYTHONPATH=. python -m backend.backtest_chan` 在真实历史数据上回测验证。

## AI 点数与支付

- 微信登录用户每次成功 AI 调用扣固定点数；失败自动退款；相同 `request_id` 幂等不重复扣费
- Web 匿名 `local-web` 用户暂不扣点（保持本地调试体验）
- 点数包下单走 `/api/orders`；模拟支付仅开发环境可用
- `APP_ENV=production` 且未配置真实微信支付时：**不会**伪造支付成功
- 真实微信支付需商户号与 API v3 密钥后再启用，当前仓库只提供可替换的订单脚手架

## 微信发布前置（外部步骤）

本仓库交付可导入、可构建、可模拟支付的工程，**不声称已完成线上审核或真实支付**。发布前需自行完成：

1. 注册小程序并替换真实 AppID / AppSecret
2. 部署 FastAPI 到 **HTTPS** 域名（国内通常需 ICP 备案）
3. 微信公众平台配置 request 合法域名
4. 选择类目并准备金融/工具相关资质（审核严格）
5. 填写用户隐私保护指引，挂载隐私政策与风险披露
6. 若上线付费：开通微信支付商户号，关闭 mock，配置正式回调

## 风险提示

本项目只提供行情观察、纪律记录和复盘辅助。任何指标都可能失效；历史数据与技术信号
不能保证未来收益。请独立判断，控制仓位，严格止损。

“热点、龙头、主力阶段、承接”均是基于涨停池和 OHLCV 的规则标签，不等于确认真实主力身份。
AI 只解读机器信号与审查纪律，不预测行情；演示数据下 AI 解读自动禁用。
