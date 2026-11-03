import { Steps, Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsTraining() {
  return (
    <DocPage
      title="训练任务 · 文档"
      description="分布式训练编排 — 基于 HyperPod Training Operator, 单卡到多节点 DDP, 全流程 Web 化, 不用 SSH。"
      meta={<Text type="secondary">v3 · 2026-06-25</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          一个训练任务 = 一个 <code>HyperPodPyTorchJob</code> + 一组 worker Pod。
          填表单, 平台帮你: Kueue 排队 → 拉镜像 → 调度到 GPU 节点 → 挂 FSx/S3 → 跑你的启动命令。
          详情页能看 Pod 状态、实时日志、GPU 监控, 也能进 Pod 终端调试。
        </UserBlock>
        <TechBlock>
          关键技术栈:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              CRD: HyperPod Training Operator + <code>HyperPodPyTorchJob</code> (非 Kubeflow PyTorchJob)
            </li>
            <li>
              启动器: <code>hyperpodrun</code> (替代 torchrun) — 启动 pod 内 :8080 HyperPodElasticAgent,
              operator 靠它判定训练完成。命令里没有 hyperpodrun 的任务会被反复重启 (见"启动命令"段)
            </li>
            <li>
              排队: Kueue ClusterQueue + LocalQueue (每工作空间一个 LocalQueue)
            </li>
            <li>
              状态: platform-worker informer watch CR <code>status.conditions</code> → 派生 phase 写 DDB
            </li>
            <li>
              机型由管理员配置 (走资源模版)。多机 GPU 通信走 NCCL
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="创建表单" subTitle="Create form">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          单页分段填写 (非分步向导), 右侧锚点跳转。每段对应一部分 CR 字段。
        </Paragraph>
        <Steps
          direction="vertical"
          current={-1}
          items={[
            {
              title: '基础信息',
              description: '显示名 + 任务名 (跟随显示名派生, DNS 友好) + 描述。工作空间取顶部下拉选中的。',
            },
            {
              title: '镜像',
              description:
                '基础镜像 (默认 pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime) 或填 ECR 私有镜像 (repo:tag)。',
            },
            {
              title: '共享存储',
              description:
                'FSx / S3 多选挂载 (勾你被授权的)。代码、数据、checkpoint 输出都放挂载的 FSx 里, 路径在启动命令自己写 — 平台不集成 Git。',
            },
            {
              title: '资源',
              description:
                '选资源模版 (admin 维护) → 带出机型 + 每节点 GPU/CPU/内存。节点数自填 (多节点 = 分布式)。GPU 可为 0 (纯 CPU 任务)。',
            },
            {
              title: '启动命令',
              description:
                '直接编写整段启动脚本 (Monaco 编辑器)。平台默认包 /bin/bash -lc 跑, 支持 shell 语法。',
            },
            {
              title: '预览',
              description: '提交前看渲染好的 HyperPodPyTorchJob YAML — 所见即所得。',
            },
          ]}
        />
      </DocSection>

      <DocSection title="启动命令与 hyperpodrun" subTitle="Launch command">
        <UserBlock>
          启动命令框填什么, 容器就用 bash 跑什么。两种典型写法:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              脚本路径: <code>bash /fsx/&lt;你的盘&gt;/code/train/start.sh</code> (脚本放 FSx 里, 自己管依赖和启动)
            </li>
            <li>
              直接命令: <code>python /fsx/.../train.py --epochs 10</code>
            </li>
          </ul>
          训练要能"正常完成"(而非反复重启), 命令需经 <code>hyperpodrun</code> 启动。
        </UserBlock>
        <TechBlock>
          实测 (DT-19): HyperPodPyTorchJob operator 的"完成"判定只认 pod 内 :8080 的
          HyperPodElasticAgent 上报, 不看容器退出码。
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              命令含 <code>hyperpodrun</code> (起 agent) → 训练结束 agent 上报 → Job 标 Completed
            </li>
            <li>
              裸命令 (无 hyperpodrun) → 没 agent → operator 认为"没真正启动", pod 退出即被
              restartPolicy=Always 拉起 → 无限重启
            </li>
            <li>
              非 torch 命令也可托管: <code>hyperpodrun ... --no-python /bin/bash -c '&lt;cmd&gt;'</code>
            </li>
          </ul>
          用户脚本 (如 start.sh) 内部自己调 hyperpodrun 即可; 平台不强制自动套 (auto_wrap 默认关)。
        </TechBlock>
      </DocSection>

      <DocSection title="状态" subTitle="Status">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            列表 / 详情有<b>两类状态</b>, 两者并存, 含义不同 — 详细见列表页 ? 图标展开的"状态说明"tip:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li>
              <b>任务状态</b> (CR phase): 任务自身生命周期。常见
              <code>Suspended (Kueue 暂挂) → Created → Created/Running (运行中) → Created/Completed → Complete</code>;
              失败转 <code>Failed</code>; 故障自动重试期间为 <code>Faulted</code>
            </li>
            <li>
              <b>排队状态</b> (Kueue 六态): 任务在调度队列里的位置。
              <code>Queued → QuotaReserved → Admitted → PodsReady</code>; 被抢占转 <code>Evicted</code>;
              结束转 <code>Finished</code>
            </li>
            <li>
              偶尔出现<b>拼接态</b>如 <code>Created/Running</code>: 多个 condition 同一刻为 True 时把 type 名用 / 拼接
            </li>
            <li>
              列表页有两个独立 filter — 按任务状态和排队状态分别过滤, chip 带计数
            </li>
            <li>
              详情页 Pod 表给每个 Pod 的 READY / 状态 / 重启次数 / 退出原因 (OOMKilled、Evicted、退出码等)
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            phase 由 platform-worker informer 从 CR <code>status.conditions</code> 派生:
            取所有 status==True 的 condition, 按 lastTransitionTime 最新优先 + 固定优先级
            (终态&gt;运行&gt;创建&gt;挂起) 取一个; 时间戳完全相同时把多个 type 名用 / 拼接得到拼接态。
            优先级表 <code>worker/phase.py:_CR_PHASE_PRIORITY</code> 完整覆盖
            <code> Failed / Complete / Completed / Succeeded / Running / Created / PodsRunning / Faulted / Suspended</code>。
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            kueue_status 是 Workload <code>status.conditions</code> 的纯镜像 (六态优先级: Finished &gt; Evicted &gt;
            PodsReady &gt; Admitted &gt; QuotaReserved &gt; Queued)。DDB 老数据上仍有迁移期小写值
            (<code>queued / started / finished</code>), 后端 <code>is_terminal</code> 兼容。
            Pod 级状态走详情页 sync 实时拉 k8s。
          </Paragraph>
        </TechBlock>
      </DocSection>

      <DocSection title="多机训练 / NCCL" subTitle="Distributed">
        <UserBlock>
          节点数 &gt; 1 = 多机分布式 (一节点一 Pod)。节点间走 NCCL all-reduce 同步梯度。
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: '判据', v: <>WORLD_SIZE &gt; 1 + 共享 MASTER_ADDR (实测 2 节点 × 2 卡 多机互通)</> },
              { k: 'NCCL', v: '镜像内置, 多机自动 handshake' },
              {
                k: 'EFA',
                v: '是否走 EFA 高速网取决于机型 — 部分机型不带 EFA 走普通网络, 高端 GPU 机型才有',
              },
              {
                k: 'GPU 监控',
                v: '详情页监控 tab 按 pod 维度过滤, 利用率不被同节点别任务的卡稀释',
              },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="检查点 / 恢复" subTitle="Checkpoint">
        <UserBlock>
          当前: 检查点由你的训练脚本自己存到挂载的 FSx (路径自己定); HyperPod 节点故障时
          operator 的 auto-resume 会自动重排重跑。崩了也可在详情页重新提交。
        </UserBlock>
        <TechBlock>
          平台侧 checkpoint 托管 (sidecar SDK + REST 上报) 是规划方向, <b>当前未实现</b> —
          没有 checkpoint sidecar、没有 <code>/trainings/&#123;id&#125;/checkpoints</code> 端点。
          现阶段检查点完全由用户脚本管理 (写 FSx), 平台不介入。
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
