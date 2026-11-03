# Chinese-English Glossary (i18n Glossary)

**English** | [简体中文](i18n-glossary.zh-CN.md)

This glossary is the single source of truth for Chinese-English translations of the platform UI, backend error messages, and in-app docs. Before adding new UI text, check this glossary first. For any business term not yet listed here, propose adding it to this glossary in your merge request (MR) before using it.

## 0. How to add translatable strings (required reading for contributors)

> English summary: every user-facing string needs a key in BOTH `zh-CN` and `en-US` catalogs (frontend and backend); run `make check-i18n` before pushing.

### Frontend

- Add a key with the same name to **both** `frontend/src/shared/i18n/locales/zh-CN/<ns>.json` and `frontend/src/shared/i18n/locales/en-US/<ns>.json`.
- In components, use `useTranslation('<ns>')`; for common words, use the `'common'` namespace. Use `{{var}}` for variable placeholders.
- Outside React (utility functions, stores, etc.), use `i18n.t(key, { ns })`, and **call it only inside a function body**, never at module top level (otherwise the string is frozen in whatever language was active at load time).
- Plurals: in English, write `_one` / `_other`; in Chinese, write only `_other`. Callers must pass a numeric `count`.
- `<Trans>` tag names must not be HTML void elements (`link`, `img`, `input`, `br`, etc.); otherwise their content is swallowed.
- Adding a new namespace: in `frontend/src/shared/i18n/resources.ts`, add the import and registration in two lines (one for zh-CN, one for en-US).
- EventSource / WebSocket / download links cannot set request headers, so their URLs must use `withLang()` to append `?lang=`.
- In-app docs pages (`features/docs/pages`) must be updated in both the `zh-CN` and `en-US` directories.

### Backend

- Add the key to **both** `services/platform-api/app/locales/zh-CN/<module>.json` and `services/platform-api/app/locales/en-US/<module>.json`, using flat naming: `<module>.<semantic>`.
- Call `t("module.key", name=value)`; strings may only use `{name}`-style placeholders.
- Do not call `t()` at module top level (it must run during request handling; the language comes from the current request).
- **Do not persist the output of `t()`** (DDB / K8s resources / generated scripts); always write such text directly in English. The one exception is the preset resource template names: they are generated in the creator's language when a workspace is created and stored in the database, and do not change when the language is switched afterward.

### Exemption markers

The guard script forbids user-facing hard-coded Chinese. When you genuinely need to keep some (a language's own name for itself, protocol fields, etc.), state the reason:

- Frontend: `// i18n-exempt: <reason>`, which must be on the **same line** as the string.
- Backend: `# i18n-exempt: <reason>`, placed on the **first line** of the statement.

### Before you submit

Run `make check-i18n`: the frontend and backend hard-coded-Chinese guard + zh/en string catalog consistency check + the i18n-related pytest subset.

### Language behavior

- Strict matching: Chinese is returned only when the language tag is exactly `zh-CN`; everything else gets `en-US`.
- API clients that send neither an `Accept-Language` header nor `?lang=` get English.
- `?lang=` takes precedence over `Accept-Language` (used by EventSource / WebSocket / download links).

---

## 1. Product terms

| Chinese | English | Notes |
|---|---|---|
| 平台 | Platform | |
| 工作空间 | Workspace | Capitalized as a product name |
| 当前工作空间 | Current Workspace | |
| 成员 | Member | |
| 普通成员 | Member | Role name; in prose you may write "regular member" |
| 工作空间管理员 | Workspace admin | |
| 平台超管 / 平台管理员 | Platform admin | Standard rendering; lowercase mid-sentence (platform admin) |
| 创建者 | Creator | |
| 开发机 | Dev Instance | |
| 训练任务 | Training Job | |
| Ray 任务 / Ray 训练 | Ray Job | |
| 单机推理 | Single-node Inference | Menu/page name (Inference Service feature) |
| 推理服务 | Inference Service | Generic term / docs; lowercase mid-sentence: inference service |
| 多机推理 | Multi-node Inference | Menu/page name (llm-d feature) |
| llm-d 推理 | llm-d Inference | Docs |
| Dynamo 推理 | Dynamo Inference | Menu/page name (Dynamo feature) |
| 任务 | Task | Generic term for all kinds of tasks |
| 任务总览 | Task Overview | |
| 资源模板 | Resource Template | |
| 规格 | Spec | For "改规格" (Resize), see Actions |
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
| 节点组 / 实例组 | Instance group | HyperPod concept |
| 额外节点 | Spare nodes | Training job spares: standby nodes that take over on failure; they count against quota |
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
| 密钥 | Secret | The platform's Secret management; do not translate as "Key" |
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
| 任务日志 | Task logs | Tab / segmented control on the logs page |
| Pod 日志 | Pod logs | Tab / segmented control on the logs page |
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

## 2. Actions

| Chinese | English |
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

## 3. Statuses (phase labels translated in the UI)

| Chinese | English |
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

The six Kueue states (Queued / QuotaReserved / Admitted / PodsReady / Evicted / Finished) and raw K8s phases are displayed as-is in both languages and are not translated.

## 4. Common fields

| Chinese | English |
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

## 5. Proper nouns that are not translated

HyperPod, SageMaker, EKS, Kueue, Workload, ClusterQueue, LocalQueue, FSx, S3, EFA, CR, Pod, namespace, CloudWatch, AMP, Prometheus, SGLang, Dynamo, llm-d, Ray, KubeRay, JupyterLab, Code Editor, SSH, Identity Center (IdC), Cognito, ECR, CodeBuild.

## 6. English style

- Menus, page titles, tab names: Title Case (`Task Overview`, `Image Hub`).
- List pages / menu names use the singular product name (Workspace, Dev Instance, Training Job …).
- Buttons, form labels, body text, hints: sentence case (`Create training job`, `Instance type`).
- Product terms capitalized in the tables (Dev Instance / Training Job / ...) are lowercase mid-sentence (dev instance / training job); Workspace, as a product name, stays capitalized mid-sentence as well.
- No trailing period on labels / buttons / column names; hints and error messages that are complete sentences end with a period.
- Use i18next plurals for counts: `{{count}} GPU` / `{{count}} GPUs`.
- Full-width parentheses (（）), full-width colons (：), and the Chinese enumeration comma (、) become half-width parentheses, half-width colons, and commas in English.
- Backend errors: complete short sentences starting with a capital letter, keeping the original technical details (field names, value ranges, placeholders).
- Errors that end with a runtime value (e.g. `... not found: {name}`) take no trailing period, so the period doesn't stick to the value.
- Date / number formatting (`toLocaleString`, etc.) passes the current language instead of relying on the browser default.
