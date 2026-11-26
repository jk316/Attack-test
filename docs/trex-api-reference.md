# TRex 客户端库 API 参考（自动探测生成）

> 生成时间: 2026-11-24T07:46:40+00:00 · 解释器: `/root/miniconda3/envs/trex311/bin/python` · Python: 3.11.16

## 1. 版本与布局

- 布局: **v3** — TRex 3.x 布局（实验床 3.08 用这个）
- stl 模块路径: `/root/fzx/Trex_Scripts/v3.08/automation/trex_control_plane/interactive/trex/stl/api.py`
- astf 模块路径: `/root/fzx/Trex_Scripts/v3.08/automation/trex_control_plane/interactive/trex/astf/api.py`
- 版本证据:
  - stl 模块 VERSION: `git-archive.dev3047580162`
- 期望版本检查: ✓ 证据中含 `3.08`
- daemon 版本（--connect）: ✓ ASTFClient: {'build_date': 'Nov  5 2025', 'build_time': '16:04:20', 'built_by': 'hhaim', 'mode': 'ASTF', 'version': 'v3.08'}

## 2. STL API（无状态）

模块: `trex.stl.api`

模块级符号索引（ASTF*/STL*）：
`ASTFErrorBadIp, STLClient, STLError, STLFlowLatencyStats, STLFlowStats, STLFlowStatsInterface, STLIPRange, STLPktBuilder, STLProfile, STLScVmRaw, STLStream, STLStreamDstMAC_ARP, STLStreamDstMAC_CFG_FILE, STLStreamDstMAC_PKT, STLTXCont, STLTXMode, STLTXMultiBurst, STLTXSingleBurst, STLTaggedPktGroup, STLTaggedPktGroupTagConf, STLTypeError, STLVM, STLVmFixChecksumHw, STLVmFixIcmpv6, STLVmFixIpv4, STLVmFlowVar, STLVmFlowVarRepeatableRandom, STLVmTrimPktSize, STLVmTupleGen, STLVmWrFlowVar, STLVmWrMa… (+31 个符号)`

#### STLClient
签名: `(username='root', server='localhost', sync_port=4501, async_port=4500, verbose_level='error', logger=None, sync_timeout=None, async_timeout=None)`

关键方法：
- `connect(self)` — Connects to the TRex server
- `disconnect(self, stop_traffic=True, release_ports=True)` — Disconnects from the server
- `acquire(self, ports=None, force=False, sync_streams=True)` — Acquires ports for executing commands
- `release(self, ports=None)` — Release ports
- `reset(self, ports=None, restart=False)` — Force acquire ports, stop the traffic, remove all streams and clear stats
- `clear_stats(self, ports=None, clear_global=True, clear_flow_stats=True, clear_latency_stats=True, clear_xstats=True)` — Clears statistics in given ports.
- `add_streams(self, streams, ports=None)` — Add a list of streams to port(s)
- `start(self, ports=None, mult='1', force=False, duration=-1, total=False, core_mask=None, synchronized=False)` — Start traffic on port(s)
- `stop(self, ports=None, rx_delay_ms=None)` — Stop port(s)
- `pause(self, ports=None)` — Pause traffic on port(s). Works only for ports that are active, and only if all streams are in Continuous mode.
- `resume(self, ports=None)` — Resume traffic on port(s)
- `wait_on_traffic(self, ports=None, timeout=None, rx_delay_ms=None)` — .. _wait_on_traffic:
- `get_stats(self, ports=None, sync_now=True)` — Gets all statistics on given ports, flow stats and latency.
- `get_port_attr(self, port)` — get the port attributes currently set
- `set_service_mode(self, ports=None, enabled=True, filtered=False, mask=None)` — based on :meth:`trex.stl.trex_stl_client.STLClient.set_service_mode_base`
- `set_l3_mode(self, port, src_ipv4, dst_ipv4, vlan=None)` — Sets the port mode to L3
- `set_l2_mode(self, port, dst_mac)` — Sets the port mode to L2
- `resolve(self, ports=None, retries=0, verbose=True, vlan=None)` — Resolves ports (ARP resolution)
- `arp(self, ports=None, retries=0, verbose=True, vlan=None)` — Resolves ports (ARP resolution)
- `ping_rpc_server(self)` — Pings the RPC server
- `get_server_version(self)` — :parameters:
- `get_server_system_info(self)` — :parameters:
- `is_connected(self)` — :parameters:
- `push_remote(self, pcap_filename, ports=None, ipg_usec=None, speedup=1.0, count=1, duration=-1, is_dual=False, min_ipg_usec=None, force=False, src_mac_pcap=False, dst_mac_pcap=False)` — Push a remote server-reachable PCAP file

#### STLStream
签名: `(name=None, packet=None, mode=<trex.stl.trex_stl_streams.STLTXCont object at 0x7fe1878973d0>, enabled=True, self_start=True, isg=0.0, flow_stats=None, next=None, stream_id=None, action_count=0, random_seed=0, mac_src_override_by_pkt=None, mac_dst_override_mode=None, dummy_stream=False, start_paused=False, core_id=-1)`
One stream object. Includes mode, Field Engine mode packet template and Rx stats

#### STLPktBuilder
签名: `(pkt=None, pkt_buffer=None, vm=None, path_relative_to_profile=False, build_raw=False, remove_fcs=True)`

#### STLVmFlowVar
签名: `(name, init_value=None, min_value=0, max_value=255, size=4, step=1, op='inc', value_list=None, split_to_cores=True, next_var=None)`

#### STLVmWrFlowVar
签名: `(fv_name, pkt_offset, offset_fixup=0, add_val=0, is_big=True)`

#### STLVmFixChecksumHw
签名: `(l3_offset, l4_offset, l4_type)`

#### STLVmFixIpv4
签名: `(offset)`

#### STLFlowStats
签名: `(pg_id, vxlan=False, ieee_1588=False)`
Define per stream basic stats

## 3. ASTF API（有状态）

模块: `trex.astf.api`

模块级符号索引（ASTF*/STL*）：
`ASTFAssociation, ASTFAssociationRule, ASTFCapInfo, ASTFClient, ASTFCluster, ASTFCmd, ASTFCmdAddStatsBase, ASTFCmdAddStatsVal, ASTFCmdAddTickStats, ASTFCmdAddTickVar, ASTFCmdAddVal, ASTFCmdCloseMsg, ASTFCmdConnect, ASTFCmdDelay, ASTFCmdDelayRnd, ASTFCmdExecTemplate, ASTFCmdJMPBase, ASTFCmdJMPCMP, ASTFCmdJMPDP, ASTFCmdJMPNZ, ASTFCmdKeepaliveMsg, ASTFCmdNoClose, ASTFCmdRecv, ASTFCmdRecvMsg, ASTFCmdReset, ASTFCmdSend, ASTFCmdSetTemplate, ASTFCmdSetTickValBase, ASTFCmdSetTickVar, ASTFCmdSetVal, ASTFC… (+60 个符号)`

#### ASTFClient
签名: `(username='root', server='localhost', sync_port=4501, async_port=4500, verbose_level='error', logger=None, sync_timeout=None, async_timeout=None)`

关键方法：
- `connect(self)` — Connects to the TRex server
- `disconnect(self, stop_traffic=True, release_ports=True)` — Disconnects from the server
- `acquire(self, force=False)` — Acquires ports for executing commands
- `release(self, force=False)` — Release ports
- `reset(self, restart=False)` — Force acquire ports, stop the traffic, remove loaded traffic and clear stats
- `clear_stats(self, ports=None, clear_global=True, clear_xstats=True, clear_traffic=True, pid_input='_')` — Clears statistics in given ports.
- `load_profile(self, profile, tunables={}, pid_input='_')` — Upload ASTF profile to server
- `start(self, mult=1, duration=-1, nc=False, block=True, latency_pps=0, ipv6=False, pid_input='_', client_mask=4294967295, e_duration=0, t_duration=0, dump_interval=0)` — Start the traffic on loaded profile. Procedure is async.
- `stop(self, block=True, pid_input='_', is_remove=False)` — Stop the traffic.
- `get_stats(self, ports=None, sync_now=True, skip_zero=True, pid_input='_', is_sum=False)` — Gets all statistics on given ports, traffic and latency.
- `get_port_attr(self, port)` — get the port attributes currently set
- `set_service_mode(self, ports=None, enabled=True, filtered=False, mask=None)` — based on :meth:`trex.astf.trex_astf_client.ASTFClient.set_service_mode_base`
- `set_l3_mode(self, port, src_ipv4, dst_ipv4, vlan=None)` — Sets the port mode to L3
- `set_l2_mode(self, port, dst_mac)` — Sets the port mode to L2
- `resolve(self, ports=None, retries=0, verbose=True, vlan=None)` — Resolves ports (ARP resolution)
- `get_server_version(self)` — :parameters:
- `get_server_system_info(self)` — :parameters:
- `is_connected(self)` — :parameters:

#### ASTFProgram
签名: `(file=None, side='c', commands=None, stream=True, s_delay=None, udp_mtu=None, addon=None)`
Emulation L7 program

关键方法：
- `send(self, buf, size=0, fill=None)` — send (l7_buffer) over TCP and wait for the buffer to be acked by peer. Rx side could work in parallel
- `recv(self, bytes, clear=False)` — recv (bytes)
- `connect(self)` — for TCP connection wait for the connection to be connected. should be the first command in the client side
- `accept(self)` — for TCP connection wait for the connection to be accepted. should be the first command in the server side
- `reset(self)` — For TCP connection send RST to peer. Should be the last command
- `delay(self, usec)` — delay for x usec
- `send_msg(self, buf, size=0, fill=None)` — send UDP message (buf)
- `recv_msg(self, pkts, clear=False)` — recv_msg (pkts)
- `set_var(self, var_id, val)` — Set a flow variable

#### ASTFProfile
签名: `(default_ip_gen, default_c_glob_info=None, default_s_glob_info=None, templates=None, cap_list=None, s_delay=None, udp_mtu=None)`
ASTF profile

#### ASTFTemplate
签名: `(client_template=None, server_template=None, tg_name=None)`
One manual template

#### ASTFTCPClientTemplate
签名: `(ip_gen, cluster=<trex.astf.trex_astf_profile.ASTFCluster object at 0x7fe1876a9350>, program=None, port=80, cps=1, glob_info=None, limit=None, cont=None, core_base=None)`
One manual template

#### ASTFTCPServerTemplate
签名: `(program=None, assoc=<trex.astf.trex_astf_profile.ASTFAssociation object at 0x7fe1876a9410>, glob_info=None)`
One server side template

#### ASTFIPGen
签名: `(dist_client, dist_server, glob=<trex.astf.trex_astf_profile.ASTFIPGenGlobal object at 0x7fe1876a8b90>)`
.. code-block:: python

#### ASTFIPGenGlobal
签名: `(ip_offset='1.0.0.0', ip_offset_server=None)`
.. code-block:: python

#### ASTFIPGenDist
签名: `(ip_range, distribution='seq', per_core_distribution=None)`
.. code-block:: python

#### ASTFCapInfo
签名: `(file=None, cps=None, assoc=None, ip_gen=None, port=None, l7_percent=None, s_glob_info=None, c_glob_info=None, limit=None, cont=None, tg_name=None, s_delay=None, udp_mtu=None)`
.. code-block:: python

## 4. 未找到的符号（版本/布局不匹配信号）

- STL: STLClient.load_profile
- ASTF: ASTFProgram.close
- ASTF: ASTFProgram.get_var
- ASTF: ASTFProgram.wait_for_flow
- ASTF: ASTFUDPClientTemplate
- ASTF: ASTFUDPServerTemplate

> 本文件由 `scripts/trex_api_probe.py` 自动生成，请勿手改；重新运行覆盖即可。
> 用法/环境事实见 `docs/trex-astf-playbook.md` 与 `trex_scripts/trex_common.py`。
