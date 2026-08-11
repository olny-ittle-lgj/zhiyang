# 知衍 AI 知识进化工坊

依据《知衍 AI 知识进化工坊系统 PRD V3.7》和 `stitch_prd` 九页设计稿实现的前后端分离应用。前端复刻深色极简实验室视觉，后端提供可直接运行的完整本地业务闭环。

## 已实现

- 产品入口、账号登录、工作台、素材管理、进化中心、游戏中心、图谱分析、个人中心、系统设置与公开分享页。
- TXT/Markdown/PDF/Word/图片/视频上传校验，手动文本和网页链接采集，状态跟踪、预览、重试和删除。
- 本地知识检索与带引用问答；配置 `DEEPSEEK_API_KEY` 后自动调用 DeepSeek。
- 自动/手动进化任务、建议审核、代理时间线和 WebSocket 流式进度接口。
- 闪卡、大富翁、概念配对题目获取、难度选择、答案校验、积分与经验持久化。
- ECharts 力导向知识图谱，支持拖拽、缩放、主题筛选和节点详情。
- 分享链接、有效期、可选密码、撤销与公开只读知识空间。
- bcrypt 密码哈希、24 小时 JWT、用户级数据隔离、操作日志和 CSV 导出。

## 本地启动

环境要求：Python 3.11+、Node.js 18+、pnpm。

```powershell
cd backend
python -m pip install -r requirements.txt
cd ..\frontend
pnpm install
cd ..
.\start-dev.ps1
```

访问：

- 前端：`http://127.0.0.1:5173`
- API 文档：`http://127.0.0.1:8000/api/docs`
- 演示账号：`demo@zhiyan.ai`
- 演示密码：`demo123456`

也可以分别启动：

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000

cd frontend
pnpm run dev
```

## 配置

复制 `backend/.env.example` 为 `.env`，或在系统环境变量中配置。默认使用 `backend/data/zhiyan.db`，首次启动自动建表并写入演示数据。

未配置外部服务时，RAGFlow、Milvus、RabbitMQ 和 DeepSeek 使用本地演示适配器，所有核心页面仍可操作。生产环境可在现有 API 边界后接入真实服务：

- `DEEPSEEK_API_KEY`：启用真实知识问答。
- 素材处理端点：可替换为 RabbitMQ/Celery + MCP 任务发布。
- `/api/ai/chat`：可将本地召回替换为 RAGFlow SDK。
- SQLite 数据访问层：接口稳定，可迁移至 MySQL 8。

## 验证

```powershell
cd backend
python -m unittest discover -s tests -v

cd frontend
pnpm run build
```

后端测试覆盖登录、素材、问答、进化审核、游戏、图谱、设置和分享主流程。

## 目录

```text
backend/
  app/              FastAPI、SQLite、认证与业务 API
  tests/            API 流程测试
frontend/
  src/components/   应用框架、模态框与提示组件
  src/pages/        各业务页面
stitch_prd/         原始设计稿与视觉规范
```
