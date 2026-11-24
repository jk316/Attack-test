# TRex ASTF 有状态攻击

> 按需加载（`load_skill("trex-astf")`）；完整参考 `docs/trex-astf-playbook.md`。
> 一句话结论：单发握手已打通（签名 tx=5 / rx≥13）；并发高 CPS 洪泛因单 IP 目标受 DP 分片限制，未跑通。

## 环境事实（实验床固定值）

- TRex daemon：`10.99.80.222`（RPC sync=4501 / async=4502），**ASTF 模式**。
  必须用 `from trex.astf.api import *` + `ASTFClient`；用 `trex_stl_lib`/`STLClient` 会报
  `server RPC config 'ASTF' vs client 'STL'`。也可直接用 `trex_common.make_astf_client()`。
- 目标：`100.1.11.3:8081`（图片接口 `/api/activities/00000000-0000-0000-0000-000000000001/image`）。
- 网关下一跳 MAC：`f4:e9:75:ee:51:69`；TRex 端口 0 MAC：`58:a2:e1:6d:89:2c`，可用 IP `100.1.11.200`。
- 目标在网关之后：TRex 端口 0 直接 ARP 目标 IP 必然失败（`Could not resolve following ports: [0]`）。

## 端口准备仪式（每个脚本开头必做，cfg 无 IP、ARP 不通）

已封装在 `trex_common.py`，直接 import，不要手写：

```python
from trex_common import make_astf_client, prepare_port

c = make_astf_client()          # ASTFClient + connect（daemon 是 ASTF 模式）
c.acquire(force=True)
c.reset()
prepare_port(c)                 # set_l3_mode 配 IP + set_l2_mode 固定网关 MAC
```

## 3.08 API 铁律（照 astf_verify.py / http_many.py）

- import：`from trex.astf.api import *`（不是 `trex_astf_lib`）。
- profile = 普通类 + `get_profile()` 返回 `ASTFProfile` 实例；文件末尾 `def register(): return Xxx()`
  （不是继承 ASTFProfile，不是 `register_profile`）。
- IP 分配：`ASTFIPGen(dist_client=…, dist_server=…, glob=ASTFIPGenGlobal(ip_offset="0.0.0.0"))`；
  参数名是 `dist_client`/`dist_server`（不是 dist_c/dist_s）；`ip_offset` 必须 `"0.0.0.0"`。
- 客户端模板：`ASTFTCPClientTemplate(ip_gen=ip_gen, port=8081, program=prog_c)`；
  参数名是 `program`/`port`（不是 prog/dport）；并发加 `cps=…, cont=True`。
- 运行：`c.load_profile(profile)` → `c.start(mult=…, duration=…, pid_input=…)`；
  `start` 没有 `ports`/`profiles` 参数；`block=False` + 自己计时 + 显式 `stop()`。
- 客户端源 IP 必须用端口网段真实 IP（`100.1.11.200~209`），乱编回包路由不回来。

## 单 IP 目标的分片限制（关键，先想清楚再写并发）

ASTF 要求每个 IP 池地址数 > DP 线程数（本机=2，即 ≥3 地址）。目标是单一真实 IP `100.1.11.3`：

- 单发（模板不设 `cps`/`cont`）可用单 IP 服务端池。
- 并发（`cont=True` + `cps`）服务端池必须 ≥3 地址（如 `["100.1.11.3","100.1.11.5"]`），
  否则报 `Profile split to DP cores error: Pool has only 1 address ... must exceed 2`；
  且 `.4/.5` 是黑洞，仅 1/N 连接打到目标（单目标攻击无干净解法）。

## 验证判据

- 先单发 `scripts/astf_verify.py`：成功签名 `tx=5 / rx≥13`（真实服务器有回包 = 握手成功）。
- 判据：`get_stats()['global']['tx_cps'] > 0` 才是真发流；`start()` 返回成功 ≠ 发流。
