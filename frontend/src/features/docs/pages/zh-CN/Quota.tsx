import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsQuota() {
  return (
    <DocPage
      title="管理中心 · 文档"
      description='资源模版定义"一份任务能用多少卡", 配额定义"工作空间总共有多少", 优先级档位决定排队顺序, 抢占开关决定能不能踢人。'
      meta={<Text type="secondary">v3.2 · 2026-08-05</Text>}
    >
      <DocSection title="三个概念" subTitle="Vocabulary" marginTop={0}>
        <UserBlock>
          <KeyValueList
            items={[
              {
                k: '资源模版',
                v: '一组固定 GPU/CPU/内存搭配。创建任务时只能选模版, 不能手填。具体机型由管理员配置 (GPU + CPU)。',
              },
              {
                k: '工作空间配额',
                v: '一个工作空间的总资源池 (建工作空间时按机型 × 数量定)。任务用超了就排队。',
              },
              {
                k: '优先级档位',
                v: '平台级档位字典 (由 HyperPod task governance 维护, admin 在管理中心建/改/删), 决定 Kueue 排队顺序。默认 common-priority (weight=80)。',
              },
            ]}
          />
        </UserBlock>
        <TechBlock>
          落到 Kueue 资源模型:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>资源模版 → Pod 的 resources 三元组 (推理 req=lim), 也是 Kueue Workload 的 podSet</li>
            <li>工作空间配额 → ClusterQueue resourceGroups + LocalQueue 映射</li>
            <li>优先级 → HyperPod ClusterSchedulerConfig.PriorityClasses (裸名 + weight 0-100) → 平台自动补 <code>-priority</code> 后缀映射到 Kueue WorkloadPriorityClass</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="资源模版" subTitle="Templates">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            资源模版 <b>按工作空间维护</b> — 入口在左侧菜单"资源模版"(选中工作空间后可见,
            所有成员能看; 新建/编辑/删除仅工作空间管理员或平台管理员)。切换工作空间会看到不同模版列表。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>新建模版 — 填名字 + GPU 数 + CPU 核数 + 内存 GiB (GPU 上限 8/节点)</li>
            <li>三类任务 (开发机 / 训练 / 推理) 共用一套模版 (2026-06-14 确定)</li>
            <li>GPU 可为 0 (纯 CPU 任务)</li>
            <li>用户创建任务时只能选模版, 不能手填 CPU/GPU/内存 (推理 req=lim 不区分)</li>
          </ul>
        </UserBlock>
        <TechBlock>
          DDB 表 <code>{'{prefix}'}-ResourceTemplates</code> (按 ws_id 分区)。后端 service 层
          通过 <code>is_ws_admin</code> 判定写权限 (平台管理员 OR 当前 ws 的 role=admin), 与前端入口同口径。
          模版是真限制层: 创建任务时资源由选中模版决定, 不可手填。
        </TechBlock>
      </DocSection>

      <DocSection title="工作空间配额 · 机型规格" subTitle="Instance spec source of truth">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>2026-07-24 起</b>建配额时下拉的机型规格 (GPU 数 / 型号 / vCPU / 内存) 全部由后端权威提供 —
            前端不再维护静态机型表。选定集群后, 机型下拉里只出现<b>该集群实际存在的机型</b>,
            每条自带规格 chip (如 <code>ml.p5.48xlarge · 8×H100 · 192 vCPU · 2048 GiB</code>) 供比较。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>集群配额总览 (跨 ws) 也会显示每 quota 的规格聚合 — 之前偶发显示 0 卡的 bug 已修</li>
            <li><b>Trainium 暂不支持分池</b> — NeuronInfo 目前不计入 accelerators, Trainium 机型只作为 CPU 池显示</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              数据源: EC2 <code>DescribeInstanceTypes</code> (硬编码 us-east-1, TTL 缓存),
              经 <code>InstanceSpec</code> 扩字段 (vCPU / 内存 GiB / GPU 型号) 后回填给 quota resources / cluster instance-groups
            </li>
            <li>
              端点级契约: <code>GET/POST/PATCH /workspaces/&#123;id&#125;/quota</code> 与
              {' '}<code>GET /clusters/&#123;tag&#125;/quotas</code> 返回的 resources[] 都带 pool/gpu_spec/gpu_type/vCpu/memoryInGib
            </li>
            <li>前端旧文件 <code>instance-types.ts</code> 已删, Dashboard / QuotaResourcePicker / Cluster 页判池均改读后端</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="FSx 目录配额" subTitle="FSx project quota">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>左侧菜单 · 管理中心 → FSx 配额</b> (仅平台管理员可见)。
            维护平台 FSx 下所有<b>一级目录</b> (<code>/fsx/&lt;team&gt;</code>) 的独立配额,
            源头就是 Lustre <code>lfs project</code> quota。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>顶部总览: FS 总容量 / 已用 / 已分配 (各目录 hard 之和)</li>
            <li>
              建目录 弹窗: 填目录名 + hard GiB + 可选<b>复用已有 team 的 gid</b>
              (跨目录共享隔离) 或让后端<b>自动新分配</b>
            </li>
            <li>改配额 弹窗: 只调 hard, soft 自动 = hard × 80% (预警线)</li>
            <li>各目录 hard 之和不得超 FS 总容量 (前后端双层校验)</li>
            <li>存量老目录 (pid=0 未纳管) 走"改配额"会顺带纳管 — 递归打 project tag + setquota</li>
          </ul>
          <Paragraph style={{ marginBottom: 0 }}>
            监控指标 (存储用量 / 剩余 / 吞吐 / IOPS) 独立在<b>左侧菜单 · 监控 → FSx</b>,
            所有登录用户可看 (是全局视图, 与 ws 无关)。
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              后端 <code>app/modules/fsx_quota</code>: 通过 <code>fsx-admin.yaml</code> DaemonSet
              (CAP_SYS_ADMIN + lustre-client) pod exec 落 <code>mkdir</code> / <code>chown</code> /
              <code>chmod 2770</code> (setgid) / <code>lfs project -s -r</code> / <code>lfs setquota</code>
            </li>
            <li>
              <b>gid vs pid</b>: gid 可复用 (跨目录共享 team 隔离); pid 永远独立 (每目录一个新 pid)
            </li>
            <li>
              读用量: 单趟 shell 一次 exec 并行拉全部目录 + 输出解析 — 避免逐目录多次 exec
              (~3.6s/目录 → 一次拉齐)
            </li>
            <li>
              <b>FS 是 source of truth</b>, 不落 DDB (与 ComputeQuota 那套 DDB + K8s CR 完全独立)
            </li>
            <li>
              监控走 CloudWatch <code>GetMetricData</code> + metric math (单维 FileSystemId),
              1h/6h/24h 三档窗口
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="优先级档位" subTitle="Priority classes">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>左侧菜单 · 管理中心 → 优先级档位</b> (仅平台管理员可见)。优先级档位是
            <b>全平台所有工作空间共用</b>的一份字典 — 任何任务都从这个列表里选档位。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              新建/编辑档位填 <b>裸名 + weight (0-100)</b>, 平台会自动补 <code>-priority</code> 后缀落到集群
              (例: 建 <code>training</code> → 集群里生成 <code>training-priority</code>)
            </li>
            <li><b>weight 是相对值</b>, 越大越优先, 不代表分钟数或百分比配额</li>
            <li>
              数值体现在两件事上:
              ① 任务排队时 weight 大的排在前面;
              ② 在抢占开关已开启的工作空间里, 高 weight 档位的任务能踢掉低 weight 档位的运行中任务
            </li>
            <li>
              改档位 weight <b>只对之后新提交的任务生效</b>, 已在跑/排队的任务沿用当时的 weight 快照, 不会重算
            </li>
            <li>
              各类任务 (训练 / 推理 / llm-d / Ray 训练 / 开发机) 默认全用 <code>common-priority</code> (weight=80), 不要删
            </li>
            <li>
              description 字段现在是<b>只读</b>展示 (官方 API 不接收该字段)
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          唯一权威源: SageMaker HyperPod task governance 的 cluster policy (<code>ClusterSchedulerConfig</code>)。
          平台<b>不再自己写 K8s WorkloadPriorityClass</b>, 而是通过官方 API 读写这份 cluster policy,
          由 HyperPod 官方 reconciler 据此生成/更新真正的 WPC。六类任务的默认档名收敛为按任务类型的统一配置,
          未配的任务类型退到全局兜底档。
        </TechBlock>
      </DocSection>

      <DocSection title="工作空间抢占开关" subTitle="Per-workspace preemption">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>左侧菜单 · 管理中心 → 工作空间抢占开关</b> (仅平台管理员可见)。每个工作空间一行开关,
            决定本空间内部能否在配额用满时, 让高优先级档位的任务踢掉低优先级档位的运行中任务。
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>何时会发生抢占？</b>必须同时满足下面三个条件, 任意一条不满足都不会发生:
          </Paragraph>
          <ol style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>该工作空间的抢占开关已开启 (LowerPriority)</li>
            <li>该工作空间的计算配额已经用满</li>
            <li>同工作空间内, 有更高优先级档位的任务正在排队</li>
          </ol>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>抢占的边界</b>:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>抢占只在同一个工作空间内部生效, 工作空间之间互不影响</li>
            <li>抢占踢的是任务的容器, 任务本身保留, 排队状态会变成 Evicted, 之后重新进入排队</li>
            <li>训练任务被踢后会自动重新排队, 需要训练侧配置了检查点容错才能续训</li>
            <li>推理服务和开发机被踢, 等于在线服务中断 / 用户会话中断</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              ClusterQueue <code>spec.preemption.withinClusterQueue</code> = Never / LowerPriority,
              per-ws 设置 (一个 ws 对应一个 cq, namespace 反推)
            </li>
            <li>
              另有 AWS 层 <code>PreemptTeamTasks</code> (跨 team 抢占), 平台默认 Never 且 UI 不暴露切换 — 工作空间之间互不影响
            </li>
            <li>抢占决策由 Kueue 控制器做, 平台只透传开关</li>
            <li>被抢占任务的 Workload 状态打成 Evicted (前端"排队状态"列可见), 重排队等空闲</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="改任务的档位" subTitle="Edit task priority">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>给具体任务换档位不在管理中心</b>, 由<b>工作空间管理员或平台管理员</b>在该工作空间的
            <b>「任务总览」</b>页操作 (点任务行的优先级档位列上的笔图标修改)。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              对<b>排队中</b>的任务换档位: 立即按新档位重新排队, 高档位前移, 任务不会重启
            </li>
            <li>
              对<b>运行中</b>的任务换档位: 平台会重建该任务的容器以让新档位生效, 训练任务自动重新排队
              (有检查点才能续训), 推理 / 开发机 = 服务中断 / 会话中断
            </li>
            <li>
              换档位本身<b>不会触发抢占</b> — 要让运行中任务被自动踢, 还得在「管理中心 → 工作空间抢占开关」把本工作空间开关设为开启
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Kueue 不允许在途 Workload 直接改 priority, 所以"改运行中任务档位"实际是:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>训练: patch CR 的 priority-class label + delete Workload, Kueue 按新 label 重建 Workload</li>
            <li>开发机/推理: patch CR label + delete Deployment, Operator 按新 label 重建 Deployment → 新 Pod</li>
            <li>排队中的任务: 改 label 后 Kueue 自动重排, 不需要重建容器</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="任务总览页" subTitle="Tasks console">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>管理 → 任务总览</b> (工作空间管理员 / 平台管理员可见, 普通成员看不到; 进入需先选定工作空间)。
            跨类型 (开发机 / 训练 / 推理) 看本工作空间所有<b>活跃</b>任务, 调整 Kueue 排队优先级。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>排队顺序列</b> (仅"排队中"范围显示) — Kueue LocalQueue 真实位置 (1=队首),
              来源 Kueue visibility API <code>positionInLocalQueue</code>; 顺序由优先级档位 + 提交时间决定
            </li>
            <li>
              <b>状态列</b> — 各任务自身生命周期 (开发机 Available / 训练 Running / 推理 DeploymentComplete 等),
              直接显原始 CR phase 不归一。可能出现拼接态如 <code>Created/Running</code>
            </li>
            <li>
              <b>过滤</b>: 范围 (排队中 / 运行中 / 全部) + 类型 (开发机 / 训练 / 推理) + 任务名搜索
            </li>
            <li>
              <b>改档位</b>: 点优先级档位列上的笔图标 — 仅对排队中任务可点 (运行中需删 Workload 重建, 单独逻辑)
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>权限: 后端 GET /tasks 走 assert_ws_admin (超管 OR ws role=admin), 不通过返 403</li>
            <li>排队顺序: Kueue visibility 扩展 API (非普通 CRD), 后端走 raw call_api 拿 pendingworkloads</li>
            <li>改档位走 priority 模块, 见上节"改任务的档位"</li>
            <li>总览只显示 active_only 任务 (排队中 + 运行中, 不含已完成 / 已失败)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
