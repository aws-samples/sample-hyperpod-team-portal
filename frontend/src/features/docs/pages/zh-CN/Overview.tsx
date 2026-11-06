import { Col, Row, Steps, Typography, theme } from 'antd';
import {
  ApartmentOutlined,
  CodeOutlined,
  ContainerOutlined,
  ControlOutlined,
  DashboardOutlined,
  HomeOutlined,
  KeyOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  ShareAltOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import DocPage, {
  ConceptCard,
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsOverview() {
  const { token } = theme.useToken();

  return (
    <DocPage
      title="HyperPod Platform · 产品概览"
      description="把 SageMaker HyperPod + EKS + Kueue 包装成 GPU 算力平台 — 团队按工作空间领配额, 工程师在浏览器里跑开发机 / 训练 / 推理。"
      meta={<Text type="secondary">v4.2 · 2026-08-05</Text>}
    >
      <div
        style={{
          padding: '32px 36px',
          borderRadius: 12,
          background:
            'linear-gradient(135deg, #0958d9 0%, #1677ff 50%, #13c2c2 100%)',
          color: '#fff',
          marginBottom: 8,
        }}
      >
        <div style={{ fontSize: 13, opacity: 0.85, letterSpacing: 1, marginBottom: 8 }}>
          HYPERPOD TEAM PORTAL
        </div>
        <div style={{ fontSize: 26, fontWeight: 600, lineHeight: '36px', marginBottom: 12 }}>
          一站式 GPU 训练 / 推理 / 开发环境工作台
        </div>
        <div style={{ fontSize: 14, lineHeight: '24px', opacity: 0.92, maxWidth: 720 }}>
          基于 AWS SageMaker HyperPod, 提供工作空间隔离 · 配额管理 · 分布式训练编排 · SGLang 推理服务 ·
          云端 Notebook 开发机 · 镜像中心 · 资源分享 — 让 ML 团队不用直面 K8s / CUDA, 也能用上 GPU 集群算力。
        </div>
      </div>

      <DocSection title="它解决了什么问题" subTitle="Why this platform">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>资源不可见</b>: 多团队共用一个 HyperPod 集群, GPU 谁占的、还剩多少、为什么排队 —
              以前要 SSH 上节点查。
            </li>
            <li>
              <b>跑任务太硬核</b>: 直接面对 Kubernetes YAML / kubectl / NCCL 环境变量, 新人上手慢。
            </li>
            <li>
              <b>资源滥用 / 误删</b>: 没有 RBAC、没有审计, 一个错误的 kubectl delete 能误删别人的任务。
            </li>
            <li>
              <b>开发机申请慢</b>: 以前申请云上 Notebook 要工单 + 手工挂盘。
            </li>
          </ul>
        </UserBlock>
        <TechBlock>
          平台是 HyperPod 的"代理 + 包装层", 不改 SageMaker 控制面:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li>
              <b>身份 / 配额</b>: Cognito 出 OIDC token; AWS CreateComputeQuota 自动落 K8s namespace +
              Kueue ClusterQueue + ResourceQuota。
            </li>
            <li>
              <b>调度</b>: Kueue ClusterQueue 做配额, LocalQueue 做工作空间映射。
            </li>
            <li>
              <b>开发机</b>: 对接 amazon-sagemaker-spaces add-on (GA), CRD workspace.jupyter.org —
              平台只做表单包装 + 状态查询, 不自研 Operator。
            </li>
            <li>
              <b>训练</b>: HyperPod Training Operator + HyperPodPyTorchJob, 用 hyperpodrun 替代 torchrun。
            </li>
            <li>
              <b>单机推理</b>: InferenceEndpointConfig (SGLang 引擎, 三层暴露 ClusterIP/内部 ALB/SageMaker endpoint)。
            </li>
            <li>
              <b>镜像 / 分享 / Token</b>: ECR 镜像中心 (含在线 CodeBuild 构建) · 资源分享 (共享 ws 内可见) · 个人 API Token。
            </li>
            <li>
              <b>controller</b>: 独立 Go 服务 (platform-controller), 各类 CR informer → derive → DDB writer, API 层永远读 DDB。
            </li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="核心模块速览" subTitle="What's in the box">
        <Row gutter={[16, 16]}>
          {[
            {
              icon: <HomeOutlined />,
              title: '工作空间',
              desc: '团队隔离单元 = K8s namespace + Kueue queue + 独立 FSx + 配额',
            },
            {
              icon: <CodeOutlined />,
              title: '开发机',
              desc: '云端 Jupyter / VS Code, 一键拉起带 GPU 的 Notebook 容器',
            },
            {
              icon: <ThunderboltOutlined />,
              title: '训练任务',
              desc: '分段表单创建分布式 PyTorch 任务, hyperpodrun 托管',
            },
            {
              icon: <RocketOutlined />,
              title: '推理服务',
              desc: 'SGLang 单机 OpenAI 兼容 API, FSx/S3 加载模型',
            },
            {
              icon: <ContainerOutlined />,
              title: '镜像中心',
              desc: 'ECR 镜像目录 + 在线 CodeBuild 构建, 三类任务复用',
            },
            {
              icon: <ShareAltOutlined />,
              title: '资源分享',
              desc: '开发机/训练/推理 一键分享给同 ws 成员, 共享只读可见',
            },
            {
              icon: <KeyOutlined />,
              title: 'Token 中心',
              desc: '个人 API Token + kv Secret, CLI/脚本免 Cognito',
            },
            {
              icon: <DashboardOutlined />,
              title: '可观测性',
              desc: 'GPU/Pod 监控 (按 pod 过滤) + 实时/历史日志 + 全任务搜索',
            },
            {
              icon: <SafetyCertificateOutlined />,
              title: '管理中心',
              desc: '任务总览 · 优先级档位 · 工作空间抢占开关 (普通成员不可见)',
            },
            {
              icon: <ApartmentOutlined />,
              title: '资源模版',
              desc: '按工作空间维护, 三类任务共用; 创建任务时只能选, 不能手填',
            },
            {
              icon: <ControlOutlined />,
              title: '审计与权限',
              desc: 'Cognito + ABAC, 全 API 调用落 DDB 审计表',
            },
          ].map((c) => (
            <Col key={c.title} xs={24} sm={12} lg={6}>
              <ConceptCard icon={c.icon} title={c.title} desc={c.desc} />
            </Col>
          ))}
        </Row>
      </DocSection>

      <DocSection title="一条典型用户路径" subTitle="Day-1 Journey">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          从拿到账号到跑出第一个推理服务的全流程。
        </Paragraph>
        <Steps
          direction="vertical"
          current={-1}
          progressDot
          items={[
            {
              title: '管理员建工作空间',
              description:
                '工作空间列表点"新建" → 选机型/数量 → 平台调 CreateComputeQuota → K8s namespace + Kueue queue 自动建好。',
            },
            {
              title: '管理员加成员 / 挂 FSx',
              description:
                '工作空间详情页 → 成员 Tab 拉用户; FSx Tab 选共享存储 (每 ws 独立 FSx)。',
            },
            {
              title: '工程师拉开发机',
              description:
                '开发机列表 → "新建" → 选资源模版 → 浏览器打开 Jupyter Lab。',
            },
            {
              title: '在开发机调通脚本',
              description: '在 Jupyter 里 import torch 跑单卡, 验证模型 forward / loss。',
            },
            {
              title: '提交分布式训练',
              description:
                '训练任务 → "新建" → 分段表单 (基础/镜像/存储/资源/启动命令/预览) → Kueue 排队 → Running 看监控。',
            },
            {
              title: '部署推理服务',
              description:
                '推理服务 → "新建" → SGLang + FSx/S3 模型路径 → 起来后按 OpenAI API 调用。',
            },
          ]}
        />
      </DocSection>

      <DocSection title="近期更新" subTitle="What's new">
        <Paragraph type="secondary" style={{ fontSize: 13 }}>
          2026-07 起主线合入的可见改动 (只列产品面表现, 底层重构见对应子页):
        </Paragraph>
        <KeyValueList
          items={[
            {
              k: '优先级档位改由官方通道维护 (2026-08-03)',
              v: (
                <>
                  管理中心 → 优先级档位: 建/改/删档现在由 SageMaker HyperPod 的官方优先级机制统一接管
                  (以前是平台自己在集群里建)。<b>你的操作方式不变</b> —— 还是在同一个页面填名字和数值;
                  只有一处变化: 数值范围收窄到 <code>0-100</code>, 描述字段改为只读展示。
                  正在跑 / 排队的任务不受影响, 迁移过程用户无感。
                </>
              ),
            },
            {
              k: '历史日志能翻更多了 (2026-07-31)',
              v: (
                <>
                  以前历史日志一屏最多只能翻几百行就到底 (CloudWatch 单次拉取有上限);
                  现在浏览页面能连续翻到几千行不断流, 首屏和每次翻页默认各给 500 行。
                </>
              ),
            },
            {
              k: 'llm-d 多机推理上线 (2026-08)',
              v: (
                <>
                  新增多机推理方式 <a href="/docs/llmd">llm-d</a>: 一个统一网关地址在前面挡, 后面可以挂多组推理副本,
                  适合模型单机装不下、又想要统一入口和缓存感知路由的场景。
                  左侧菜单新增"llm-d 推理"入口, 创建表单里能分别配置网关和推理副本的资源规格。
                </>
              ),
            },
            {
              k: '新增队列 / 配额监控页 (2026-08)',
              v: (
                <>
                  监控菜单新增"队列 / 配额": 选一个工作空间, 就能看到该空间的算力配额用了多少、还剩多少、
                  有多少任务在排队等待 —— 任务长时间 Pending 时先来这里看一眼, 比翻日志快。
                </>
              ),
            },
            {
              k: 'FSx 目录配额 (2026-07-22)',
              v: (
                <>
                  管理中心新增"FSx 配额": 平台管理员可以给每个共享存储目录单独设容量上限
                  (超了自动拦, 不会一个团队把盘写满影响别人)。
                </>
              ),
            },
            {
              k: 'FSx 用量监控 (2026-07-22)',
              v: '监控菜单新增"FSx": 存储用了多少、还剩多少、读写有多忙, 1 小时 / 6 小时 / 24 小时随意切, 所有登录用户可看。',
            },
            {
              k: '配额页机型信息更准了 (2026-07-24)',
              v: '建配额时下拉框里的机型规格 (GPU 数量 / 型号) 改由后端实时核对, 修复了集群配额总览偶尔显示 0 卡的问题。',
            },
            {
              k: '镜像仓库名不再强加前缀 (2026-07-24)',
              v: '镜像中心在线构建时, 你填的仓库名会原样使用 (支持带路径, 如 team-a/my-model), 平台不再自动加固定前缀。',
            },
            {
              k: '日志能查到更早以前了 (2026-07-20)',
              v: '历史日志现在会自动归档到长期存储, 排障时能翻到比以前更久之前的记录。',
            },
          ]}
        />
      </DocSection>

      <DocSection title="文档索引" subTitle="Read next">
        <KeyValueList
          items={[
            { k: '工作空间', v: '团队隔离 + 配额 + FSx + 成员管理 (含跟 K8s 的对应关系)。' },
            { k: '开发机', v: 'Jupyter / VS Code 云端 Notebook。EBS / 镜像 / 端口转发 / 状态。' },
            { k: '训练任务', v: '分布式 PyTorch + Kueue 排队 + hyperpodrun + 拼接态状态。' },
            { k: '推理服务', v: 'SGLang 单机, FSx/S3 模型, 三种调用方式 + 部署/删除态全集。' },
            { k: 'llm-d 推理', v: '单机装不下的大模型跨节点部署, 统一网关入口 + 多组推理副本。' },
            { k: '镜像中心', v: 'ECR 目录 + 在线 CodeBuild 构建 + 版本 tag 管理。' },
            { k: '资源分享', v: '开发机/训练/推理 分享给同 ws 成员, 共享只读列表。' },
            { k: 'Token 中心', v: '个人 API Token + kv Secret, CLI/脚本免登。' },
            { k: '管理中心', v: '资源模版 (ws 级) · 优先级档位 · 工作空间抢占开关 · 任务总览。' },
            { k: '可观测性', v: '指标 (DCGM + Pod, pod 过滤) · 实时/历史日志 · 全任务 Insights 搜索。' },
            { k: '技术架构', v: 'EKS + HyperPod + Spaces + Kueue + platform-controller + DDB 单源 全景。' },
            { k: '关于权限', v: '三类身份 + 三个判定门 + 能力矩阵, 看完就能回答"谁能做什么"。' },
            { k: '常见问题', v: '任务卡 Pending / FSx 挂载 / hyperpodrun / 权限 排错。' },
          ]}
        />
        <Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12, color: token.colorTextTertiary }}>
          每个子页面按"用户视角 / 技术原理"双层叙述 — 上面教你怎么用, 下面解释底层怎么跑。
          产品文档入口在右上角 (新窗口打开), 文档站独立浏览模式, 内部链接互通。
        </Text>
      </DocSection>
    </DocPage>
  );
}
