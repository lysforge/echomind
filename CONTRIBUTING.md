# 参与 EchoMind 开发与贡献

感谢关注并欢迎为 **EchoMind（声忆）** 贡献代码、文档、硬件桥接适配或问题反馈！

## 仓库目录结构

```text
echomind/
├── backend/                  # FastAPI + SQLite + WebSocket 网关 + 音频管线
│   ├── app/
│   │   ├── main.py           # 服务入口与静态前端托管
│   │   ├── db.py             # SQLite Schema、分类标签预设与年龄阶段推算
│   │   ├── routers/          # REST API（认证、专辑/媒体、房间播控、成员、定时等）
│   │   ├── gateways/         # /ws/speaker、/xiaozhi/v1/、/ws/web 实时双向网关
│   │   └── services/         # 语音交互引擎、采集器、英语课程、声纹识别与 -16 LUFS 均衡
│   └── tests/                # 全链路自动化测试
├── web/                      # React 19 + TypeScript + Tailwind CSS v4 前端控制台
│   └── src/
│       ├── pages/            # 前台听音台与后台内容工坊页面
│       └── components/       # 全局播放器、主题切换器、语音交互抽屉与通用弹窗
├── clients/                  # 通用智能音箱桌面/树莓派桥接脚本
├── Dockerfile                # 多阶段生产容器构建
└── docker-compose.yml        # 一键自托管编排配置
```

## 本地开发环境启动

### 1. 启动后端开发服务

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

> 本地需预先安装 `ffmpeg`（macOS 可执行 `brew install ffmpeg`，Ubuntu/Debian 可执行 `sudo apt install ffmpeg`）。

### 2. 启动前端热更新开发服务

```bash
cd web
npm install
npm run dev
```

开发模式下可直接运行 `npm run build` 检查 TypeScript 类型与 Vite 打包输出。

## 运行自动化测试

```bash
cd backend
.venv/bin/pytest -v
```

> 测试用例默认在独立临时目录 (`ECHOMIND_DATA_DIR`) 运行，不会污染仓库 `data/` 下的本地库文件。

## 提交代码规范

- 保持简洁清晰的提交信息，例如：`feat: ...`、`fix: ...`、`docs: ...`、`refactor: ...`。
- 提交 PR 前请确保通过 `cd web && npm run build` 与 `cd backend && pytest -v`。
- 请勿在源码或配置文件中硬编码本机绝对路径、个人密钥或测试数据库文件。
