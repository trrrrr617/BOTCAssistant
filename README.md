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


---

*proudly presented by tr!&Claude code, currently in alpha testing*
