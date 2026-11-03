import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsWorkspace() {
  return (
    <DocPage
      title="工作空间 · 文档"
      description="工作空间 (Workspace) 是平台的最小隔离单元 — 一个团队 = 一个 Workspace = 一个 K8s namespace + 一份配额 + 一组成员。"
      meta={<Text type="secondary">v2.1 · 2026-07-27</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            可以把一个工作空间想成"团队的项目目录": 它装着团队的 GPU 配额、共享数据盘、谁能进来,
            以及这里跑的所有开发机/训练任务/推理服务。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>一个用户可以加入多个工作空间 (顶部下拉切换)。</li>
            <li>不同工作空间互不可见 — 你看不到隔壁组在跑什么任务。</li>
            <li>配额是工作空间维度结算: 整个团队的卡用完了, 后续任务排队。</li>
          </ul>
        </UserBlock>
        <TechBlock>
          每个 Workspace 在 AWS / K8s 里对应:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <code>HyperPod ComputeQuota</code> — SageMaker 控制面对象, 是配额的源头
            </li>
            <li>
              <code>Namespace</code> <code>hyperpod-ns-{'{name}'}</code> — Kueue 自动建,
              所有 Pod / PVC 都落这里
            </li>
            <li>
              <code>ResourceQuota</code> + <code>LimitRange</code> — K8s 原生硬限,
              防 namespace 跨 ws 占资源
            </li>
            <li>
              <code>Kueue ClusterQueue + LocalQueue</code> — 排队 + 优先级, 一对一映射
            </li>
            <li>
              <code>FSx Lustre 挂载</code> — 子目录隔离防跨租户读;
              一个 ws 可挂多块盘 + 接受其他团队共享 (见下方「存储 · FSx」);
              一级目录走 <code>lfs project</code> quota 限额, 监控走 CloudWatch (见下方「FSx 目录配额 + 监控」)
            </li>
            <li>
              <code>IAM Role</code> — 每 Workspace 一个 Role (Pod Identity targetTags 不可用)
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="怎么建" subTitle="Create a workspace">
        <UserBlock>
          <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>左侧菜单点"工作空间" → 右上"新建工作空间"(仅平台管理员可见)。</li>
            <li>填名称 (slug)、展示名、描述 — namespace 自动派生为 <code>hyperpod-ns-{'{name}'}</code></li>
            <li>选机型 + 数量 (从集群可用机型里挑, 决定这个工作空间的配额)。</li>
            <li>提交后立即跳详情页 — 后续在 FSx Tab 挂存储、成员 Tab 拉人。</li>
          </ol>
        </UserBlock>
        <TechBlock>
          后端 <code>POST /workspaces</code> 一笔事务做 4 件事:
          <ol style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              调 AWS{' '}
              <code>SageMaker.CreateComputeQuota</code> — 这是唯一会动 SageMaker 控制面的写操作
            </li>
            <li>
              SageMaker 控制器自动 <code>kubectl apply</code> 出 namespace + ResourceQuota + ClusterQueue
            </li>
            <li>
              平台 WorkspaceController (轻量, 3 PD 实现) 给 namespace 写 annotation +{' '}
              Finalizer + 漂移检测
            </li>
            <li>
              落 DDB <code>Workspaces</code> + <code>WorkspaceMembers</code> + <code>AuditLog</code> 三张表
            </li>
          </ol>
          整个流程 P95 &lt; 8s。失败时 <code>CreateComputeQuota</code> 是幂等的, 重试安全。
        </TechBlock>
      </DocSection>

      <DocSection title="数据模型" subTitle="DDB schema">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          工作空间元数据走 DDB 单源 — RDS / Redis 已移除。
        </Paragraph>
        <KeyValueList
          items={[
            { k: '主表', v: <code>hypd-{'{env}'}-Workspaces</code> },
            { k: 'PK / SK', v: <><code>WS#{'{ws_id}'}</code> / <code>META</code></> },
            { k: 'GSI-1', v: <>by-cluster · 按 cluster_id 反查 ws 列表</> },
            { k: 'GSI-2', v: <>by-name · 按 slug name 唯一性闸 (创建时 conditional check)</> },
            {
              k: '关联表',
              v: (
                <>
                  <code>WorkspaceMembers</code> · <code>ResourceIndex</code> ·{' '}
                  <code>AuditLog</code>
                </>
              ),
            },
            { k: 'TTL', v: 'Workspaces 永久; AuditLog 90 天 (TTL field)' },
          ]}
        />
      </DocSection>

      <DocSection title="成员与权限" subTitle="Membership & RBAC">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>admin (工作空间管理员)</b> — 加/移成员、配 FSx、看任务总览、调任务优先级
            </li>
            <li>
              <b>member (普通成员)</b> — 创建/查看自己的开发机/训练/推理, 但不能改配额/优先级
            </li>
            <li>
              另有 <b>平台管理员</b> (跨工作空间) — 仅做新建工作空间 + 平台级抢占开关
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          权限不直接写到 K8s RoleBinding, 改在平台 API 层做 ABAC 闸:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              身份: Cognito ID Token (sub = user_id, custom:is_admin = bool)
            </li>
            <li>
              角色查 DDB <code>WorkspaceMembers</code> · PK <code>WS#{'{ws_id}'}</code> ·{' '}
              SK <code>USR#{'{user_id}'}</code>
            </li>
            <li>
              所有写 API 走 <code>assert_ws_admin(ws_id, user)</code> 装饰器, 不通过 → 403 + AuditLog
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="存储 · FSx Lustre" subTitle="Storage · FSx">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            FSx Lustre 是工作空间的高速共享盘 — 训练数据集、checkpoint、代码都放这里,
            开发机 / 训练 / 推理的 Pod 都能挂载到约定的目录上读写。
            管理员在工作空间详情页的 <b>FSx Tab</b> 维护挂载, 普通成员只能用被授权给自己的目录。
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>一条挂载 = 一块 FSx 上的一个目录</b>。管理员添加挂载时填:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>
              <b>挂载 ID</b> (mount_id) — 这块盘在本工作空间里的别名, 小写字母开头
              (如 <code>team-data</code>)
            </li>
            <li>
              <b>挂载点</b> (mount_path) — Pod 容器内的路径, 默认按 ID 联动为{' '}
              <code>/fsx/&lt;mount_id&gt;</code>, 可改
            </li>
            <li>
              <b>FSx 文件系统 + 一级目录</b> — 选哪块盘的哪个子目录 (可再手填更深的子路径)
            </li>
          </ul>
          <Paragraph style={{ marginBottom: 6 }}>
            一个工作空间可以挂<b>多块</b> FSx / 多个目录 — 既有"自己团队的盘",
            也可以是别的团队<b>共享</b>过来的盘。
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            <b>「主」标记</b>: 创建表单的 FSx 列表里, 带紫色「主」标签的是<b>本团队自己的盘</b>
            (归属本工作空间的主用户组), 会排在最前; 其余是被授权访问的<b>其他团队 / 共享盘</b>。
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>挂载 (attach)</b> — 走 <code>fsx-csi-driver</code>。平台为每条挂载建一对
            cluster-scoped 的 PV (读写各一个) + 工作空间 namespace 内的 PVC。
            子目录隔离靠 PV 的 <code>mountname</code> 拼到 team 子目录层:
            Lustre 客户端只挂到该子目录, 跨租户读被内核硬拦, 不靠应用层判断。
            添加挂载时后端会<b>探测该目录的属主 gid</b> 并固化进权限记录。
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>授权 (grant)</b> — 挂载本身不等于成员能用。管理员在 FSx Tab 对每条挂载
            <b>逐个给成员授权</b>, 选 <code>ro</code> (只读) 或 <code>rw</code> (读写)。
            成员只有拿到授权后, 才能在创建开发机 / 训练时看到并挂这个目录。
          </Paragraph>
          <KeyValueList
            items={[
              { k: '授权表', v: <code>hypd-{'{env}'}-MountPermissions</code> },
              {
                k: 'PK / SK',
                v: (
                  <>
                    <code>{'{workspace_id}'}</code> /{' '}
                    <code>MOUNT#{'{mount_id}'}#USER#{'{username}'}</code>
                  </>
                ),
              },
              {
                k: 'GSI',
                v: (
                  <>
                    <code>username-index</code> — 开发机创建时查"我在本 ws 被授权的所有挂载"
                  </>
                ),
              },
              {
                k: '关键字段',
                v: (
                  <>
                    <code>access</code> (ro/rw) · <code>gid</code> · <code>mount_path</code> ·{' '}
                    <code>pvc_name_rw</code> / <code>pvc_name_ro</code> · <code>granted_by</code>
                  </>
                ),
              },
            ]}
          />
          <Paragraph style={{ marginBottom: 0, marginTop: 8 }}>
            <b>gid 与「主」的真相</b>: 工作空间有一个固有的主用户组{' '}
            <code>primary_gid</code> (= Pod 的 <code>runAsGroup</code>, 第一次挂 FSx 时固化在
            workspace metadata)。<code>list_permitted_mounts</code> 把{' '}
            <code>gid == primary_gid</code> 的挂载标 <code>is_primary=true</code> 并排到列表第一 —
            这就是前端「主」标签的来源。所有被授权挂载的 gid 会进 Pod 的{' '}
            <code>supplementalGroups</code>, 让进程对这些目录有组级读写权。
          </Paragraph>
        </TechBlock>
      </DocSection>

      <DocSection title="存储 · FSx 目录配额 + 监控" subTitle="FSx quota & monitoring">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>目录配额</b> (管理中心 → FSx 配额, 仅平台超管):
            平台接入的每块 FSx 下所有一级目录都有一份独立的 project quota,
            决定它最多能用多少 GiB。总览显示 FS 总容量 / 已用 / 已分配,
            列表列出每个一级目录的 gid / pid / 已用 / soft / hard / 使用率, 可弹窗建目录 / 改配额。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li><b>多 FSx</b>: 页面右上角下拉选盘 (展示 <code>名字 (fs-id)</code>, 名字取 AWS Tags[Name]), 默认选第一块; 建目录 / 改配额都作用在当前选中的那块</li>
            <li><b>建目录</b>: 填目录名 + hard GiB + 可选复用已有 team 的 gid; 不传 gid = 后端自动新分配 (新 team)</li>
            <li><b>soft 自动 = hard × 80%</b> (预警线)</li>
            <li><b>容量约束</b>: 各目录 hard 之和 ≤ 该盘总容量 (前后端双层校验, 按盘独立算)</li>
            <li><b>改配额</b>: pid=0 的历史目录会顺带纳管 (递归打 tag + setquota)</li>
          </ul>
          <Paragraph style={{ marginBottom: 0 }}>
            <b>FSx 监控</b> (监控 → FSx, 所有登录用户可看): 6 张 CloudWatch 趋势图 —
            剩余容量 / 存储使用率 / 网络吞吐 / 磁盘吞吐 / 磁盘 IOPS / 元数据 CPU,
            时段可选 1h / 6h / 24h, 同样右上角下拉选盘。与工作空间无关, 是**全局视图**。
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>配额落地</b> (`app/modules/fsx_quota`): 走 fsx-admin Deployment (CAP_SYS_ADMIN + lustre-client,
            由 <code>deploy/cluster-prereq.sh fsxadmin</code> 生成), 通过 pod exec 执行 (下面 <code>&lt;root&gt;</code> = <code>/fsx-mnt/&lt;fs-id&gt;</code>):
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li><code>mkdir &lt;root&gt;/&lt;name&gt;</code> + <code>chown :&lt;gid&gt;</code> + <code>chmod 2770</code> (setgid, 保子目录 gid 继承)</li>
            <li><code>lfs project -p &lt;pid&gt; -r -s &lt;root&gt;/&lt;name&gt;</code> — 打 project tag</li>
            <li><code>lfs setquota -p &lt;pid&gt; -b &lt;soft&gt;G -B &lt;hard&gt;G &lt;root&gt;</code></li>
          </ul>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>多 FSx 挂载</b>: <b>一个</b> fsx-admin pod 挂<b>多块</b>盘 —— 每块盘一对 PV/PVC,
            挂载点 <code>/fsx-mnt/&lt;fs-id&gt;</code> (fs-id 来自 cdk.json <code>platformFsxFilesystems</code> 的
            逗号分隔 fs-id, 注入后端 env <code>PLATFORM_FSX_FILESYSTEMS</code>; fs-id 天然路径安全, 直接当挂载点)。
            一个挂载点只能对应一块盘, 故用中性父目录 <code>/fsx-mnt</code> 分盘, 不嵌在某块盘根下。
            未配进 <code>PLATFORM_FSX_FILESYSTEMS</code> 的 fs 无法做配额 (后端直接报错, 因为拼不出挂载根)。
            <b>要求 Lustre 2.15</b> — 2.12 上 project quota 不生效 (setquota 静默成功, quota 读回 0)。
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>gid vs pid</b>: gid 可复用 (跨目录共享 team 隔离); pid 永远独立 (每目录一个新 pid,
            便于按目录独立限额)。<b>FS 是 source of truth</b>, 不落 DDB。
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>读用量</b>: 单趟 shell 一次 exec 并行拉全部目录的 <code>lfs project</code> + <code>lfs quota</code>
            并输出解析 — 避免逐目录多次 exec (从 ~3.6s/目录 → 一次拉齐)。
          </Paragraph>
          <KeyValueList
            items={[
              { k: '配额 API', v: <><code>GET/POST/PATCH /api/v1/admin/fsx-quota/directories[/&lt;name&gt;]</code> · 平台超管 · 均带 <code>filesystem_id</code> (GET 走 query, POST/PATCH 走 body)</> },
              { k: '选盘 API', v: <><code>GET /api/v1/monitoring/fsx/filesystems</code> — 返回 <code>{'{filesystemId, name, capacityGib}'}</code> (name = AWS Tags[Name]) 给配额/监控页下拉, 展示为 <code>名字 (fs-id)</code></> },
              { k: '监控 API', v: <><code>GET /api/v1/monitoring/fsx/metrics?filesystem_id=fs-xxx&amp;range=1h|6h|24h</code> · 所有登录用户</> },
              { k: '监控指标', v: <>6 条 — 一次 <code>GetMetricData</code>; 额外维度值 (FileServer / StorageTargetId) 先 <code>ListMetrics</code> 探实际编号再拉, 不写死</> },
              { k: '目标 FSx', v: <>由 <code>PLATFORM_FSX_FILESYSTEMS</code> env (<code>fs-id</code> 逗号分隔) 定候选池, 前端下拉选具体一块</> },
              { k: 'IAM', v: <>api_role 需 <code>cloudwatch:GetMetricData</code> + <code>cloudwatch:ListMetrics</code></> },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="列表页交互" subTitle="List page UX">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>顶部摘要 chip 行</b>: 空间数 · 成员总数 · 当前总 GPU 配额使用 (M/P 卡 + 百分比)
              — 数字汇总自当前可见空间, GPU 用量按 &lt;70% / 70-90% / ≥90% 三档分色
            </li>
            <li>
              <b>卡片视图 GPU 行</b>: 进度条样式 (与详情页 renderUsageRow 同款), 配色阈值一致
            </li>
            <li>
              <b>卡片 / 列表的快捷编辑入口</b> (仅平台管理员): 直接跳详情页对应 Tab —
              成员 / FSx / S3, 通过 URL 参数 <code>?tab=members|fsx|s3</code> 直达
            </li>
            <li>
              <b>列表视图与卡片视图切换</b>: 右上角 Segmented; 卡片 = 视觉浏览, 列表 = 表格排序
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="存储 · S3" subTitle="Storage · S3">
        <UserBlock>
          S3 用于模型 / 数据集这类对象存储: 管理员在工作空间的 <b>S3 Tab</b> 添加 bucket /
          prefix 挂载, 训练任务可直接挂载读取, 推理服务可用于模型 prefetch。
          与 FSx 一样按 <code>mount_id</code> + 挂载点管理。
        </UserBlock>
        <TechBlock>
          走 <code>s3-csi-driver</code> (Mountpoint for S3)。注意 S3 挂载是对象语义 (非
          POSIX 文件系统), 适合顺序读大文件 / 数据集; 频繁随机写、rename、追加写场景仍走 FSx。
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
