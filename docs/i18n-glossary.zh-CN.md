# 中英术语表 (i18n Glossary)

[English](i18n-glossary.md) | **简体中文**

平台界面、后端报错、应用内文档的中英翻译以本表为唯一依据。新增界面文字时先查本表; 表里没有的业务名词, 先在 MR 里提议加入本表再用。

## 0. 如何新增可翻译文案 (贡献者必读)

> English summary: every user-facing string needs a key in BOTH `zh-CN` and `en-US` catalogs (frontend and backend); run `make check-i18n` before pushing.

### 前端

- 在 `frontend/src/shared/i18n/locales/zh-CN/<ns>.json` 和 `frontend/src/shared/i18n/locales/en-US/<ns>.json` **两边都**加同名 key。
- 组件内 `useTranslation('<ns>')`; 通用词用 `'common'` 命名空间。变量用 `{{var}}` 占位。
- React 之外 (工具函数、store 等) 用 `i18n.t(key, { ns })`, 且**只能在函数体内调用**, 不得写在模块顶层 (否则冻结在加载时的语言)。
- 复数: 英文写 `_one` / `_other`, 中文只写 `_other`; 调用时必须传数值型 `count`。
- `<Trans>` 的标签名不能是 HTML void 元素 (`link`、`img`、`input`、`br` 等), 否则内容会被吞掉。
- 新增命名空间: 在 `frontend/src/shared/i18n/resources.ts` 加两行 (zh-CN 与 en-US 各一行) 的 import 与注册。
- EventSource / WebSocket / 下载链接设不了请求头, URL 必须用 `withLang()` 附带 `?lang=`。
- 应用内文档页 (`features/docs/pages`) 要同时改 `zh-CN` 与 `en-US` 两个目录。

### 后端

- 在 `services/platform-api/app/locales/zh-CN/<module>.json` 和 `services/platform-api/app/locales/en-US/<module>.json` **两边都**加 key, 采用扁平命名 `<module>.<semantic>`。
- 调用 `t("module.key", name=value)`, 文案里只允许 `{name}` 形式的占位符。
- `t()` 不得在模块顶层调用 (必须在请求处理期间, 语言来自当前请求)。
- **不要把 `t()` 的输出持久化** (DDB / K8s 资源 / 生成的脚本); 这类文本一律直接写英文。例外是资源模板预置名称: 它在建工作空间时按创建者语言生成并落库, 此后不随语言切换。

### 豁免标记

守门脚本禁止面向用户的硬编码中文。确需保留 (语言自称、协议字段等) 时写明原因:

- 前端: `// i18n-exempt: <原因>`, 必须与该字符串在**同一行**。
- 后端: `# i18n-exempt: <原因>`, 写在该语句的**第一行**。

### 提交前

运行 `make check-i18n`: 前后端硬编码中文守门 + 中英文案表一致性 + i18n 相关 pytest 子集。

### 语言行为

- 严格匹配: 语言标签恰好为 `zh-CN` 才返回中文, 其余一律 `en-US`。
- 无 `Accept-Language` 头也无 `?lang=` 的 API 客户端得到英文。
- `?lang=` 优先于 `Accept-Language` (供 EventSource / WebSocket / 下载链接使用)。

---

## 1. 产品名词

| 中文 | English | 备注 |
|---|---|---|
| 平台 | Platform | |
| 工作空间 | Workspace | 首字母大写作产品名 |
| 当前工作空间 | Current Workspace | |
| 成员 | Member | |
| 普通成员 | Member | 角色名; 行文中可写 regular member |
| 工作空间管理员 | Workspace admin | |
| 平台超管 / 平台管理员 | Platform admin | 统一译法; 在句中小写 (platform admin) |
| 创建者 | Creator | |
| 开发机 | Dev Instance | |
| 训练任务 | Training Job | |
| Ray 任务 / Ray 训练 | Ray Job | |
| 单机推理 | Single-node Inference | 菜单/页面名 (推理服务 feature) |
| 推理服务 | Inference Service | 泛指 / 文档; 句中 inference service |
| 多机推理 | Multi-node Inference | 菜单/页面名 (llm-d feature) |
| llm-d 推理 | llm-d Inference | 文档 |
| Dynamo 推理 | Dynamo Inference | 菜单/页面名 (Dynamo feature) |
| 任务 | Task | 泛指各类任务 |
| 任务总览 | Task Overview | |
| 资源模板 | Resource Template | |
| 规格 | Spec | "改规格"见动作 |
| 机型 | Instance type | |
| 资源池 | Resource pool | GPU 资源池 = GPU pool, CPU 资源池 = CPU pool |
| 配额 | Quota | |
| 机器配额 | Instance quota | |
| 配额用量 | Quota usage | |
| 优先级 | Priority | |
| 优先级档位 | Priority class | |
| 抢占 | Preemption | |
| 排队顺序 / 排队位置 | Queue position | |
| 集群 | Cluster | |
| 节点 | Node | |
| 节点组 / 实例组 | Instance group | HyperPod 概念 |
| 额外节点 | Spare nodes | 训练任务 spares: 故障时顶替的备用节点, 会占配额 |
| 拓扑感知调度 | Topology-aware scheduling (TAS) | Kueue TAS |
| 副本 | Replica | |
| 容器 | Container | |
| 网关 | Gateway | |
| 端点 | Endpoint | |
| 调用方式 | Invocation | |
| 镜像 | Image | |
| 镜像中心 | Image Hub | |
| 镜像构建 | Image build | |
| Token 中心 | Token Center | |
| API Token | API token | |
| 密钥 | Secret | 平台的 Secret 管理, 不译成 Key |
| 资源分享 | Sharing | |
| 存储 | Storage | |
| 挂载 | Mount | |
| 挂载路径 | Mount path | |
| 共享存储 | Shared storage | |
| 数据集 | Dataset | |
| 日志 | Logs | |
| 实时日志 | Live logs | |
| 历史日志 | Log history | |
| 日志流 | Log stream | |
| 任务日志 | Task logs | 日志页 Tab / 分段器 |
| Pod 日志 | Pod logs | 日志页 Tab / 分段器 |
| 整任务搜索 | Search all logs | |
| 监控 | Monitoring | |
| 指标 | Metric | |
| 终端 | Terminal | |
| 入口脚本 | Entry script | |
| 启动命令 | Launch command | |
| 环境变量 | Environment variables | |
| 标签 | Labels | K8s label |
| 权限 | Permission | |
| 角色 | Role | |
| 管理中心 | Admin Console | |
| 产品文档 | Docs | |
| 故障诊断手册 | Troubleshooting Runbook | |
| API 文档 | API Reference | |

## 2. 动作

| 中文 | English |
|---|---|
| 创建 / 新建 | Create / New |
| 启动 | Start |
| 停止 | Stop |
| 删除 | Delete |
| 克隆 | Clone |
| 改规格 | Resize |
| 编辑 | Edit |
| 保存 | Save |
| 取消 | Cancel |
| 确认 | Confirm |
| 刷新 | Refresh |
| 复制 | Copy |
| 关闭 | Close |
| 查看 | View |
| 下载 | Download |
| 搜索 | Search |
| 重置 | Reset |
| 提交 | Submit |
| 预览 | Preview |
| 连接 | Connect |
| 分享 | Share |

## 3. 状态 (界面翻译过的 phase 标签)

| 中文 | English |
|---|---|
| 待调度 | Pending |
| 创建中 | Creating |
| 部署中 | Deploying |
| 待部署 | Pending deployment |
| 运行中 | Running |
| 已完成 | Succeeded |
| 已失败 | Failed |
| 已停止 | Stopped |
| 异常 | Degraded |
| 删除中 | Deleting |
| 已挂起 | Suspended |

Kueue 六态 (Queued / QuotaReserved / Admitted / PodsReady / Evicted / Finished) 与 K8s 原始 phase 在两种语言下都原样显示, 不翻译。

## 4. 通用字段

| 中文 | English |
|---|---|
| 名称 | Name |
| 描述 | Description |
| 状态 | Status |
| 状态详情 | Status details |
| 操作 | Actions |
| 创建时间 | Created at |
| 开始时间 | Started at |
| 结束时间 | Ended at |
| 运行时长 | Duration |

## 5. 不翻译的专有名词

HyperPod, SageMaker, EKS, Kueue, Workload, ClusterQueue, LocalQueue, FSx, S3, EFA, CR, Pod, namespace, CloudWatch, AMP, Prometheus, SGLang, Dynamo, llm-d, Ray, KubeRay, JupyterLab, Code Editor, SSH, Identity Center (IdC), Cognito, ECR, CodeBuild。

## 6. 英文风格

- 菜单、页面标题、Tab 名: Title Case (`Task Overview`, `Image Hub`)。
- 列表页 / 菜单名用单数产品名 (Workspace, Dev Instance, Training Job …)。
- 按钮、表单 label、正文、提示: sentence case (`Create training job`, `Instance type`)。
- 表格里首字母大写的产品名词 (Dev Instance / Training Job / ...) 在句中用小写 (dev instance / training job); Workspace 作为产品名在句中也保持大写。
- 标签 / 按钮 / 列名末尾不加句号; 完整句子的提示与报错加句号。
- 数量用 i18next 复数: `{{count}} GPU` / `{{count}} GPUs`。
- 中文里的全角括号、全角冒号、顿号在英文里改为半角括号、半角冒号、逗号。
- 后端报错: 以大写开头的完整短句, 保留原有的技术细节 (字段名、取值范围、占位符)。
- 以运行时值结尾的报错 (如 `... not found: {name}`) 不加句号, 避免句号粘在值上。
- 日期 / 数字格式化 (`toLocaleString` 等) 传当前语言, 不依赖浏览器默认。
