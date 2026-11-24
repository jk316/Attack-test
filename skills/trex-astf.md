# TRex ASTF 有状态攻击

> 按需加载（`load_skill("trex-astf")`）；完整参考 `docs/trex-astf-playbook.md`。
> 一句话结论：单发握手已打通（签名 tx=5 / rx≥13）；并发高 CPS 洪泛因单 IP 目标受 DP 分片限制，未跑通。

## 环境事实（实验床固定值）

- TRex daemon：`10.99.80.222`（RPC sync=4501 / async=4500），**ASTF 模式**。
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

## 实测 API 签名（v3.08，来自 docs/trex-api-reference.md）

> `scripts/trex_api_probe.py` 实测生成。写脚本以这里的签名为准，不要凭记忆。
> 完整签名（含 STL / 未找到符号）见 `docs/trex-api-reference.md`，拿不准时以此为准。

### ASTFClient
`(username='root', server='localhost', sync_port=4501, async_port=4500, verbose_level='error', logger=None, sync_timeout=None, async_timeout=None)`

- `connect(self)` / `disconnect(self, stop_traffic=True, release_ports=True)`
- `acquire(self, force=False)` — 无 ports 参数（区别于 STL）
- `release(self, force=False)`
- `reset(self, restart=False)` — 无 ports 参数
- `set_service_mode(self, ports=None, enabled=True, filtered=False, mask=None)`
- `set_l3_mode(self, port, src_ipv4, dst_ipv4, vlan=None)`
- `set_l2_mode(self, port, dst_mac)` — dst_mac 是位置参数（无默认值）
- `resolve(self, ports=None, retries=0, verbose=True, vlan=None)`
- `load_profile(self, profile, tunables={}, pid_input='_')` — 传 profile 对象
- `start(self, mult=1, duration=-1, nc=False, block=True, latency_pps=0, ipv6=False, pid_input='_', client_mask=4294967295, e_duration=0, t_duration=0, dump_interval=0)` — 无 ports 参数
- `stop(self, block=True, pid_input='_', is_remove=False)`
- `get_stats(self, ports=None, sync_now=True, skip_zero=True, pid_input='_', is_sum=False)`
- `get_port_attr(self, port)`

### ASTFProgram
`(file=None, side='c', commands=None, stream=True, s_delay=None, udp_mtu=None, addon=None)`

- `send(self, buf, size=0, fill=None)` — 发 TCP 负载
- `recv(self, bytes, clear=False)` — 第二参是 `clear`（bool），不是超时
- `connect(self)` — 客户端侧第一个命令
- `accept(self)` — 服务端侧第一个命令
- `reset(self)` — 最后一个命令（发 RST）
- `delay(self, usec)` — 单位是微秒 usec（不是毫秒）
- `send_msg(self, buf, size=0, fill=None)` / `recv_msg(self, pkts, clear=False)` — UDP 收发
- `set_var(self, var_id, val)`

### 模板与 IP 分配
- `ASTFProfile(default_ip_gen, default_c_glob_info=None, default_s_glob_info=None, templates=None, cap_list=None, s_delay=None, udp_mtu=None)`
- `ASTFTemplate(client_template=None, server_template=None, tg_name=None)`
- `ASTFTCPClientTemplate(ip_gen, cluster=…, program=None, port=80, cps=1, glob_info=None, limit=None, cont=None, core_base=None)`
- `ASTFTCPServerTemplate(program=None, assoc=…, glob_info=None)`
- `ASTFIPGen(dist_client, dist_server, glob=…)`
- `ASTFIPGenGlobal(ip_offset='1.0.0.0', ip_offset_server=None)` — 注意默认 `'1.0.0.0'`
- `ASTFIPGenDist(ip_range, distribution='seq', per_core_distribution=None)`
- `ASTFCapInfo(file=None, cps=None, assoc=None, ip_gen=None, port=None, l7_percent=None, s_glob_info=None, c_glob_info=None, limit=None, cont=None, tg_name=None, s_delay=None, udp_mtu=None)`

## 3.08 铁律（签名之外的坑）

- import 名：`from trex.astf.api import *`（不是 `trex_astf_lib`）。
- profile 结构：普通类 + `get_profile()` 返回 `ASTFProfile` 实例；文件末尾 `def register(): return Xxx()`
  （不是继承 ASTFProfile、不是 `register_profile`）。
- `ip_offset` 必须 `"0.0.0.0"`（`ASTFIPGenGlobal` 默认 `"1.0.0.0"`，会把目标 IP 偏移）。
- `recv` 第二参是 `clear`（bool）；`delay` 单位是微秒 usec——别当成「超时 ms」。
- `start` 用 `block=False` + 自己计时 + 显式 `stop()`（默认 `block=True` 会阻塞/被掐死）。
- 客户端源 IP 用真实网段 `100.1.11.200~209`，乱编回包路由不回来。

## 单 IP 目标的分片限制（关键，先想清楚再写并发）

ASTF 要求每个 IP 池地址数 > DP 线程数（本机=2，即 ≥3 地址）。目标是单一真实 IP `100.1.11.3`：

- 单发（模板不设 `cps`/`cont`）可用单 IP 服务端池。
- 并发（`cont=True` + `cps`）服务端池必须 ≥3 地址（如 `["100.1.11.3","100.1.11.5"]`），
  否则报 `Profile split to DP cores error: Pool has only 1 address ... must exceed 2`；
  且 `.4/.5` 是黑洞，仅 1/N 连接打到目标（单目标攻击无干净解法）。

## 验证判据

- 先单发 `scripts/astf_verify.py`：成功签名 `tx=5 / rx≥13`（真实服务器有回包 = 握手成功）。
- 判据：`get_stats()['global']['tx_cps'] > 0` 才是真发流；`start()` 返回成功 ≠ 发流。
