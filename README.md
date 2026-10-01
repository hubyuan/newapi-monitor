# NewAPI Group Monitor

NewAPI 分组监控面板 — 一个独立的只读监控工具，展示 [NewAPI](https://github.com/Calcium-Ion/new-api) 各分组的请求成功率、首字时间（TTFT）和流量趋势。

**不需要修改 NewAPI 代码**，独立部署，Token 隐藏在服务端，用户无需登录即可查看。

## 功能

- **分组级监控** — 按 NewAPI 的 channel group 聚合，不暴露单个渠道细节
- **成功率** — 从最新 N 条真实请求日志中统计，反映真实流量比例
- **首字时间** — 提取 NewAPI 日志中的 FRT（First Response Time），不是总耗时
- **趋势图表** — 每张卡片内嵌迷你时间线图（成功/失败柱状图 + 首字趋势线）
- **分组筛选** — 选择关注的分组，选项保存在浏览器 localStorage
- **自动刷新** — 默认每 5 分钟自动刷新，服务端缓存 2 分钟
- **暗色模式** — 自动跟随系统主题
- **零依赖** — Python 标准库，无需安装任何第三方包

## 快速开始

### 直接运行

```bash
export NEWAPI_BASE_URL=http://127.0.0.1:3000   # NewAPI 地址
export NEWAPI_TOKEN=sk-xxxxxxxxxxxxxxxx         # 管理员 Token

python3 server.py
```

打开 `http://localhost:8898` 即可。

### Docker

```bash
docker build -t newapi-monitor .

docker run -d \
  --name newapi-monitor \
  -p 8898:8898 \
  -e NEWAPI_BASE_URL=http://host.docker.internal:3000 \
  -e NEWAPI_TOKEN=sk-xxxxxxxxxxxxxxxx \
  newapi-monitor
```

### Docker Compose

```bash
cp .env.example .env
# 编辑 .env 填入你的配置
docker compose up -d
```

## 配置

所有配置通过环境变量传入：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `NEWAPI_BASE_URL` | 是 | — | NewAPI 服务地址，如 `http://127.0.0.1:3000` |
| `NEWAPI_TOKEN` | 是 | — | 管理员 API Token（`role=100` 的用户 Token） |
| `PORT` | 否 | `8898` | 监听端口 |
| `LOG_LIMIT` | 否 | `400` | 每分组拉取的日志条数，越多覆盖时间越长 |
| `CACHE_TTL` | 否 | `120` | 统计结果缓存秒数 |
| `EXCLUDE_GROUPS` | 否 | — | 排除的分组，逗号分隔，如 `test,debug` |

也可以通过命令行参数指定端口：

```bash
python3 server.py --port 9000
```

## 反向代理

推荐通过 Nginx / Caddy 等反向代理暴露服务：

**Caddy:**
```
monitor.example.com {
    reverse_proxy 127.0.0.1:8898
}
```

**Nginx:**
```nginx
server {
    server_name monitor.example.com;
    location / {
        proxy_pass http://127.0.0.1:8898;
    }
}
```

## 工作原理

```
浏览器  ──→  server.py (:8898)  ──→  NewAPI Admin API
              │
              ├─ GET /              → 返回 index.html
              ├─ GET /data/channels → 代理渠道列表（过滤敏感字段）
              └─ GET /data/stats    → 按分组聚合日志统计
```

### 统计算法

1. 从渠道列表自动发现所有分组
2. 每个分组**独立查询**最新 N 条日志（不区分成功/失败，一次拉取）
3. 统计 `type=2`（成功）和 `type=5`（失败）的数量，计算真实比例
4. 从日志 `other` 字段提取 `frt`（First Response Time）作为首字时间
5. 4 线程并发拉取，结果缓存 2 分钟

### 安全设计

- 管理员 Token **只存在于服务端**，前端不接触
- `/data/channels` 接口过滤掉 `key`、`base_url`、`model_mapping` 等敏感字段
- 前端纯只读，无任何写操作

## 要求

- Python 3.7+
- NewAPI（[Calcium-Ion/new-api](https://github.com/Calcium-Ion/new-api)）实例
- 管理员 Token（用于读取渠道和日志 API）

## 许可

[MIT](LICENSE)
