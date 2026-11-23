# 攻防实验控制台 · React 前端

实验为中心的新版前端，取代原 `frontend/` 三件套（原生 HTML/JS/CSS）。视觉沿用 `output/ui-mockup.html` 设计稿（暗色 + 荧光绿 `#C6FF3D` + 琥珀 `#FFB547`）。

## 运行

```bash
cd frontend-react
npm install
npm run dev        # http://localhost:5173
npm run build      # 生产构建 → dist/
```

开发环境已配置 `/api`、`/ws` 代理到后端 `http://localhost:8000`（`vite.config.js`）。

## 技术栈

- Vite 6 + React 18 + React Router 6 + ECharts 5
- 纯 CSS（设计 token 在 `src/styles/global.css`，与设计稿同源）
- 字体：Space Grotesk / Inter / JetBrains Mono（Google Fonts）

## 目录结构

```
src/
├── main.jsx / App.jsx         入口 + 路由
├── styles/global.css          设计系统（颜色/字体/圆角/组件类）
├── lib/
│   ├── mock.js                模拟数据（实验列表、状态六态）
│   └── api.js                 数据访问层（USE_MOCK 开关）
├── components/
│   ├── ui.jsx                 Button/Icon/StatusBadge/Modal/AnimatedNumber
│   ├── Sidebar.jsx            侧边导航
│   ├── charts.jsx             RttChart（双轴）+ LiveChart（实时）
│   ├── CreateExperimentModal.jsx
│   └── HitlModal.jsx
└── pages/
    ├── ExperimentList.jsx     实验列表（过滤 + 5s 轮询 + 详情/新建入口）
    ├── ExperimentDetail.jsx   实验详情（KPI + 拨测曲线 + 攻击时间线 + 推理流）
    └── MonitorPage.jsx        实时观测（IP 可达 / 交换机流量 / 业务健康）
```

## 对接后端

`src/lib/api.js` 顶部 `USE_MOCK = true` 时走本地模拟数据；后端 Plan 1（SQLite + REST/WS，见 `docs/front-end.md` §8）就绪后置 `false` 即可对接真实契约。

- REST：`listExperiments` / `getExperiment` / `createExperiment` / `stopExperiment` / `deleteExperiment` / `getMetaOptions`
- WebSocket：`connectExperimentSocket(runId, handlers)`（预留断线重连 + `after_seq` 补齐位）
