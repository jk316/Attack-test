# TRex ASTF 有状态攻击避坑手册

**适用范围**: TRex v3.08 + 本实验床（TRex daemon `10.99.80.222`，目标 `100.1.11.3`）
**更新时间**: 2026-11-24
**状态**: 单发握手已全部验证通过（签名见下）；cps 并发项待最终确认（见 §8）

---

## 1. 一句话结论

有状态攻击（真实三次握手 + HTTP GET flood）在本实验床**已打通**：
`ASTF daemon` + 端口 L2 固定网关 MAC + 3.08 profile 正确写法 + `load_profile → start(pid_input)`。
单发验证的**成功签名**：`tx=5 包 / rx≥13 包`。

---

## 2. 环境事实（实验床固定值，写死即可）

| 项 | 值 | 说明 |
|----|-----|------|
| TRex daemon | `10.99.80.222`，RPC sync=4501 / async=4502 | 端口对约定：async = sync + 1 |
| daemon 模式 | 由启动参数决定：`--stl`（无状态）/ `--astf`（有状态），一进程一模式 | 客户端必须用匹配的 client，否则报 `server RPC config 'STL' vs client 'ASTF'` |
| 目标 | `100.1.11.3:8081`（图片接口 `/api/activities/00000000-0000-0000-0000-000000000001/image`） | 拨测端口 3000 是登录接口，同一系统 |
| cfg | `/etc/trex_cfg.yaml` **只配了 MAC、没有 IP** | 端口 IP 必须运行时配置 |
| TRex 端口 0 | 100G，MAC `58:a2:e1:6d:89:2c`，可用 IP `100.1.11.200`（与目标同网段） | 客户端源 IP 用它，回包才路由得回来 |
| 网关 MAC | `f4:e9:75:ee:51:69` | **ARP 永远失败**（目标不回 ARP），出口 MAC 直接固定网关 MAC |
| 客户端库 | 客户端机器上 `from trex.astf.api import *`（3.08 包名，**不是** `trex_astf_lib`） | 版本必须与 daemon 一致 |

---

## 3. 端口准备仪式（每个 ASTF 脚本开头必做）

cfg 无 IP、ARP 不通，所以每轮 `acquire/reset` 之后都要走这套（已封装在 `scripts/astf_verify.py` / `scripts/astf_get_flood.py` 的 `configure_port()`）：

```python
c.acquire(force=True)
c.reset()

c.set_service_mode(ports=[PORT], enabled=True)   # 仪式必须在 service mode 期间
c.set_l3_mode(PORT, "100.1.11.200", "100.1.11.3")  # 配端口 IP（内部顺带做 ARP，会失败但配置已生效）
try:
    c.resolve(ports=[PORT], retries=3)            # 预期失败：目标不回 ARP
except Exception:
    pass
c.set_l2_mode(PORT, dst_mac="f4:e9:75:ee:51:69")  # 兜底：固定网关 MAC（注意：也要求 service mode 开启！）
c.set_service_mode(ports=[PORT], enabled=False)
```

⚠️ 两个易错点：
- `set_l2_mode` 在 service mode **关闭后**调用会报 `port service mode must be enabled`；
- `set_l3_mode` 报「Could not resolve following ports」时**配置其实已生效**，属预期，继续走 L2 兜底。

---

## 4. 3.08 ASTF API 铁律（本次踩坑全集）

### 4.1 profile 文件结构（照官方 `examples/astf/http_many.py`）

```python
from trex.astf.api import *

class ProfXxx():                    # 普通类，不继承 ASTFProfile
    def get_profile(self, **kwargs):
        prog_c = ASTFProgram()
        prog_c.connect()
        prog_c.send(b"GET ... HTTP/1.1\r\nHost: ...\r\n\r\n")
        prog_c.recv(1, 10000)       # 收到至少 1 字节（超时 ms）
        prog_c.delay(2000)          # 保持连接（下载攻击靠这个吊住服务器）
        prog_c.reset()

        prog_s = ASTFProgram()      # 服务端占位：打真实服务器时不会被用到，但惯例必须定义
        prog_s.accept()
        prog_s.recv(1)
        prog_s.send(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

        ip_gen = ASTFIPGen(
            glob=ASTFIPGenGlobal(ip_offset="0.0.0.0"),   # 必须 0：否则真实目标 IP 会被偏移
            dist_client=ASTFIPGenDist(ip_range=["100.1.11.200", "100.1.11.209"], distribution="seq"),
            dist_server=ASTFIPGenDist(ip_range=["100.1.11.3", "100.1.11.3"], distribution="seq"),
        )
        temp_c = ASTFTCPClientTemplate(ip_gen=ip_gen, port=8081, program=prog_c, cps=50, cont=True)
        temp_s = ASTFTCPServerTemplate(program=prog_s)
        template = ASTFTemplate(client_template=temp_c, server_template=temp_s)
        return ASTFProfile(default_ip_gen=ip_gen, templates=[template])

def register():                     # 末尾必须是这个，不是 register_profile()
    return ProfXxx()
```

### 4.2 运行流程（客户端）

```python
pid = c.load_profile("/tmp/prof.py")   # 返回值可能是 None
c.start(pid_input=pid or "", mult=1, duration=30, block=False)  # 没有 profiles 参数！
# block 语义不可靠 → 非阻塞启动 + 自己 sleep/轮询 + 显式 stop()
```

### 4.3 反例对照（都是本次实际踩过的坑）

| ❌ 错误写法 | 报错/现象 | ✅ 正确 |
|-----------|----------|--------|
| `from trex_astf_lib.api import *` | ModuleNotFoundError | `from trex.astf.api import *` |
| `class Prof(ASTFProfile)` + `super().__init__(default_ip_gen=...)` | `ASTFProfile.__init__() missing 1 required positional argument` | 普通类 + `get_profile()` **返回** ASTFProfile 实例 |
| 文件末尾 `register_profile(...)` | `NameError: register_profile is not defined` | `def register(): return ProfXxx()` |
| 模板不传 `ip_gen` | `missing 1 required positional argument: 'ip_gen'` | 传**合并的 ASTFIPGen 对象**（不是 ASTFIPGenDist） |
| 模板传 `dport=` | `unexpected keyword argument 'dport'` | 参数名是 `port`（先 `inspect.signature` 探测） |
| `c.start(profiles=[...])` | `unexpected keyword argument 'profiles'` | `load_profile` → `start(pid_input=...)` |
| `start(pid_input=None)` | `'NoneType' object has no attribute 'split'` | `pid or ""`，再失败回退 `"_"` |
| `block=True` 依赖 start 阻塞 | 0.0 秒返回、洪水被掐死 | `block=False` + 自己计时 + `stop()` |
| 模板只给 `cps` 不给 `cont` | 30 秒只有 1 个连接（tx 恒定 5） | 加 `cont=True`（**待验证**，见 §8） |
| `ip_offset="1.0.0.0"` | 目标 IP 被偏移、请求发错地方 | `"0.0.0.0"` |
| 客户端 IP 用假网段 `16.0.0.x` | 服务器回包路由不回来 | 用端口网段真实 IP（`100.1.11.200~209`） |

---

## 5. 验证套路

1. **先单发**：`python3 scripts/astf_verify.py` —— 成功签名 `tx=5 / rx≥13`；
2. **再加压**：`python3 scripts/astf_get_flood.py --cps 50 --duration 30 [--client-ips ...] [--dwell ...]`；
3. 观测：ping 监控（RTT/丢包）+ HTTP 拨测（`http.url` 探针，`--noproxy` 修复后基线应 >0）。

---

## 6. 模型需要知道 vs 不需要知道（提示词设计结论）

**只给模型这 3 条**：

1. 3.08 API 写法铁律（§4.1/4.2 骨架 + §4.3 反例中的「必错项」）；
2. 客户端源 IP 必须用 TRex 端口网段真实 IP（本床 `100.1.11.200~209`），乱编回包回不来；
3. 验证套路（先单发看 `tx=5/rx≥13` 签名，再加压）。

**封装进代码、不进模型脑袋**（待抽 helper，见 §8）：

- daemon 模式判断 / RPC 端口 / 双实例路由；
- 端口准备仪式整套（§3）；
- 网关 MAC、ARP 失败原因等实验床事实。

---

## 7. 现有脚本索引

| 脚本 | 用途 |
|------|------|
| `scripts/astf_verify.py` | 单发验证：握手 + GET，打印 tx/rx 签名 |
| `scripts/astf_get_flood.py` | GET flood：`--cps/--duration/--client-ips/--dwell` 可调，10 秒进度打印 |

---

## 8. 待办（诚实标注）

- [ ] `cont=True` + `cps=50` 的并发建连效果**尚未跑通验证**——若无效，官方姿势是 profile `cap_list=[ASTFCapInfo(cps=…)]`；
- [ ] 抽 `trex_astf_helpers.py`：封装 `connect_and_prepare()`（§3 仪式 + 连接参数），模型生成脚本只 import 调用；
- [ ] 提示词注入「模型 3 条铁律」（§6）；
- [ ] 服务器上未入库的 `trex_stl_*` 自定义工具收进仓库；
- [ ] daemon 双实例（STL 4501 + ASTF 4503）落地后，工具层做模式路由。
