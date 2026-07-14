# A 股散户纪律系统

把《炒股挣钱讲座》中的“顺势而为、仓位管理、止损纪律、买入三问”
落成一个可执行、可复盘的 Web 工具。系统用于管理交易纪律，不构成投资建议，
也不承诺收益。

## 功能

- 市场温度：展示主要指数，并按涨停、炸板与成交数据判断春播、夏长、秋收、冬藏
- 个股分析：日 K、成交量、MA5/10/20/60、趋势与支撑/压力提示
- 仓位管理：334 仓位目标、持仓盈亏、止损与破 60 日线提醒
- 交易台账：买入前强制回答“逻辑、资金、空间”并设置止损
- 复盘统计：胜率、盈亏比、月度盈亏、违纪次数与常见错误

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

## 风险提示

本项目只提供行情观察、纪律记录和复盘辅助。任何指标都可能失效；历史数据与技术信号
不能保证未来收益。请独立判断，控制仓位，严格止损。
