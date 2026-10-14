# 接手与下一阶段清单

## B 线先做

1. 审核 docs/model.md 的演示参数，用真实/经批准参数替换，保存 MicrogridConfig JSON；修改后重跑三类 Demo 和测试。
2. 与 A/C 冻结 docs/contracts.md v0.1，统一 request_id、设备 ID、状态读取位置、单区间命令时长及错误码。
3. 在完整依赖环境跑 pytest、三类 Demo、40 seed 实验。先看失败案例，不以成功比例替代安全审查。

## 与 A 线对接

将 api.invoke 或三个独立算法函数包装进真正 MCP 服务。工具权限分离；优化器无执行权限；执行入口必须再次绑定最新状态和相同 plan 内容，不能只信字符串 plan_id 或外部 pass=true。现有哈希不是认证，公开服务须另做权限。

control_step 是本地编排样例，不是 AgentArts Workflow。Phase 2 默认最多重规划一次；计划 Phase 5 的最多两次由 A 的工作流显式设置。增加 Single-Agent/Multi-Agent 适配时，使用相同 seed 和时间区间，不把 deterministic optimizer 改名冒充 Agent。

## 与 C 线对接

Simulator 的 get_state 输出只含 JSON；apply_action 返回 accepted；step 后返回 applied 和真实变化的 SOC/功率。C 负责 IoTDA 遥测与命令映射、MQTT 重连/超时/串行化、时间序列存储、事件触发和 Backend。

Simulator 目前是快速离散实验器：没有后台 sleep 循环，没有云端线程。持续设备进程必须由调度器按 5 秒节拍运行并定义无新命令时的安全策略；不能把实验器的停表行为直接当真实设备保护逻辑。

## 尚待完成

ECS/容器联调、完整依赖锁定、真实 MCP/IoTDA、频率/孤岛模型（只在明确扩展范围后做）、持久化和跨进程并发控制、实际云端延迟指标、三种 Agent/规则统一对照、真实设备参数审查。


## 第二轮审查后对接注意

实例级线程锁已实现，但不能跨 worker/进程保证命令幂等；多个 Backend worker 不应各自维护独立的同名设备仿真器。`control_step` 是多个公开调用组成的本地编排，不是分布式事务。

ACK 与 applied 都带实际复验的 `validation`；后端应保留该证据。取消旧 pending 用 `cancel_pending_action()`，查看历史状态用 `get_receipt(plan_id)`，不要用反复重发来查询。

JSON 时长不再接受字符串/布尔值，request_id/plan_id 不再接受任意对象转换。验证和潮流请求省略顶层 request_id 会继承 plan.request_id，显式冲突则拒绝；请同步共享 Schema。

实验的 `failure_kind` 区分不可行、安全拒绝、运行故障和执行审计失败。`batch` 非零退出码不能直接忽略；无云集成时仍不能把本地耗时宣称为端到端云延迟。
