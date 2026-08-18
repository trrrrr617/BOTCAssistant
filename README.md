# 血染钟楼说书人辅助 (Blood on the Clocktower — Storyteller Assistant)

本地联机的说书人自动化系统。由 Python 程序替代真人说书人，自动完成身份发放、夜晚角色行动、信息发配、白天聊天计时、提名投票与胜负判定。

**当前剧本示例**:「夜半狂欢」(The Midnight Oasis, Zets) — 7-15 人, 23 个角色

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量(可选;不配置则运行在纯模板模式)
cp .env.example .env
# 编辑 .env 填入 LLM API key

# 4. 启动
python run.py
```

浏览器访问:

- 大厅: <http://localhost:5000/>
- 说书人控制台: <http://localhost:5000/st/>(创建房间后跳转)
- 玩家页: <http://localhost:5000/p/>(加入房间后跳转)

同一局域网内,玩家用 `http://<本机IP>:5000/` 访问。

## 项目结构

```
blood-on-the-clocktower-st/
├── run.py                      入口
├── config.py                   全局配置
├── server/                     后端
│   ├── routes.py               HTTP 路由
│   ├── socketio_gateway.py     WebSocket 事件
│   ├── room/                   房间与玩家
│   ├── engine/                 游戏状态机
│   ├── roles/                  角色实现(阶段二补全)
│   └── llm/                    LLM 接入(阶段三)
├── templates/                  Jinja2 模板
├── static/                     CSS / JS / 图片
└── docs/                       设计稿
```

## 设计原则

- **信息提供,不做戏剧化叙事**:所有系统文案与 LLM 输出保持事实陈述风格
- **状态机集中**:所有变更走 `GameState.mutate()`,便于存档/回放/调试
- **角色即策略对象**:`BaseRole` 子类钩子承载所有规则,引擎只调度
- **LLM 关键节点介入**:仅在 8 个决策/创作节点调用,均有模板降级

## 路线图

- [x] 阶段 0:项目骨架 + LV 风格美术
- [ ] 阶段 1:核心状态机 + 通用投票工具
- [ ] 阶段 2:23 角色规则补全
- [ ] 阶段 3:LLM 接入
- [ ] 阶段 4:美术打磨

---

*proudly presented by tr!&Claude code, currently in alpha testing*
