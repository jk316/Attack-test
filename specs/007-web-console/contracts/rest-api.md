# 契约：REST API（Web 控制台）

**特性目录**: `specs/007-web-console/` | **日期**: 2026-11-19 | **对应 FR**: FR-001、FR-015~FR-018

## 端点总览

| 方法 | 路径 | 用途 | 新增/现状 |
|------|------|------|:---:|
| GET | / | 控制台单页 | 现状 |
| GET | /static/* | 静态资源（style.css / app.js） | 现状 |
| POST | /api/upload/pcap | PCAP 上传（服务端校验，G3 改造） | 改造 |
| GET | /api/experiment/status | 实验运行状态查询 | 现状 |
| POST | /api/experiment/start | 参数校验回显（不启动实验；实际启动走 WebSocket） | 现状 |
| POST | /api/experiment/stop | 通道外停止实验 | 现状 |
| GET | /api/experiment/defaults | 实验默认值（单一来源，G4 新增） | 新增 |

## POST /api/upload/pcap

- 请求：`multipart/form-data`，字段 `file`。
- 服务端校验（007-3 决议，G3 改造后强制）：
  1. 文件名非空；否则 400 `{"success": false, "error": "未选择文件"}`。
  2. 扩展名白名单 `.pcap / .pcapng / .cap`（不区分大小写）；否则 400 `{"success": false, "error": "不支持的文件类型（仅 .pcap/.pcapng/.cap）"}`。
  3. 大小上限 100MB；否则 413 `{"success": false, "error": "文件超过大小上限（100MB）"}`。
  4. 校验失败的文件一律不落盘。
- 成功（200）：

```json
{
  "success": true,
  "file_path": "data/uploads/ab12cd34_sample.pcap",
  "file_name": "sample.pcap",
  "size_bytes": 1048576
}
```

- `file_path` 为相对项目根路径（`data/uploads/<8位随机前缀>_<原始文件名>`），可直接回填表单并经 start_experiment 引用。

## GET /api/experiment/status

- 成功（200）：`{"running": true}` 或 `{"running": false}`。
- 语义：进程级实验运行状态（实现 G2 后应明确为「任意会话存在运行中实验」或提供按会话维度——以 tasks 阶段设计为准；契约保证 `running` 布尔字段稳定）。

## POST /api/experiment/start

- 请求体（JSON）：

```json
{ "target_ip": "100.1.11.20", "pcap_path": "", "log_path": "data/experiment.jsonl", "max_iters": 20, "no_improve_limit": 5 }
```

- 成功（200）：参数校验回显，**不启动实验**（提示经 WebSocket 启动）；字段校验同 ws-messages.md 的 start_experiment。

## POST /api/experiment/stop

- 成功（200）：`{"success": true, "message": "停止请求已发送"}`。

## GET /api/experiment/defaults（新增，G4）

- 成功（200）：

```json
{ "target_ip": "100.1.11.20", "max_iters": 20, "no_improve_limit": 5 }
```

- 语义：从 `src/config/experiment.json` 读取（启动时加载，运行期修改需重启生效），供前端表单初值与后端 StartRequest 兜底默认共用（配置单一来源，宪法六）。

## 错误约定

- 所有接口错误返回 JSON：`{"success": false, "error": "<中文原因>"}`（status 接口除外，其语义仅 `running` 布尔）。
- 服务端异常不外泄堆栈，仅返回可读原因（与 ws error 一致）。
