# A 股散户纪律系统

把《炒股挣钱讲座》中的“顺势而为、仓位管理、止损纪律、买入三问”
落成一个可执行、可复盘的 Web 工具。系统用于管理交易纪律，不构成投资建议，
也不承诺收益。

## 功能

- 市场温度：展示主要指数，并按真实涨停/炸板/跌停家数与沪指量能比判断春播、夏长、秋收、冬藏
- 优选个股：用量能、洗盘、价量重心与启动信号生成可解释的观察清单
- 个股分析：支持 A 股与港股通 5 位代码，展示日 K、成交量、均线、支撑/压力与缠论中枢/类三买结构
- 仓位管理：334 仓位目标、持仓盈亏、止损与破 60 日线提醒
- 交易台账：买入前强制回答“逻辑、资金、空间”并设置止损
- 复盘统计：胜率、盈亏比、月度盈亏、违纪次数与常见错误
- AI 教练（可选）：基于 Cursor SDK（Grok 4.5 high fast）解读个股信号、审查买入三问、生成复盘报告

## 技术栈

- 前端：React、TypeScript、Vite、Apache ECharts
- 后端：FastAPI、SQLite、akshare

## 本地运行

### 1. 后端

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

接口文档位于 <http://localhost:8000/docs>。

### 2. 前端

另开终端：

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。开发服务器会将 `/api` 代理到后端。

## 验证

```bash
source .venv/bin/activate
pytest

cd frontend
npm run build
```

## 数据说明

实时行情通过 akshare 获取。上游网络不可用时，界面会明确显示降级状态并使用演示数据，
避免将模拟行情误认为实时行情。持仓与台账默认保存在本地 SQLite 数据库中。
港股价格以港币记录，仓位和盈亏按中行港币折算价换算为人民币汇总。

缠论结构（分型、笔、中枢、类三买）由 `backend/chan.py` 的纯函数计算，
可用 `PYTHONPATH=. python -m backend.backtest_chan` 在真实历史数据上回测验证。

AI 教练需要设置 `CURSOR_API_KEY` 环境变量（Cursor Dashboard → Integrations 获取）。
未设置时 AI 接口返回 503，其余功能不受影响。AI 只解读机器算出的信号和审查交易纪律，
不预测行情；行情降级为演示数据时 AI 解读会自动禁用。

## 风险提示

本项目只提供行情观察、纪律记录和复盘辅助。任何指标都可能失效；历史数据与技术信号
不能保证未来收益。请独立判断，控制仓位，严格止损。
