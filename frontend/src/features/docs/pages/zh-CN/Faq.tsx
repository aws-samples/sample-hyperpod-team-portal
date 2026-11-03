import { Collapse, Typography } from 'antd';
import DocPage, { DocSection } from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsFaq() {
  return (
    <DocPage
      title="常见问题 · 文档"
      description='跑训练 / 推理 / 开发机 容易遇到的坑 — 按 "现象 → 原因 → 操作" 写。'
      meta={<Text type="secondary">v2 · 2026-06-23</Text>}
    >
      <DocSection title="任务排队 / 状态" subTitle="Queueing" marginTop={0}>
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: 'Q · 训练任务一直 Pending, 怎么回事?',
              children: (
                <>
                  <Paragraph style={{ marginBottom: 6 }}>
                    <Text strong>可能原因:</Text>
                  </Paragraph>
                  <ul style={{ paddingLeft: 20 }}>
                    <li>工作空间配额已满 — 别的任务占着, 没卡给你</li>
                    <li>选的资源模版要的 GPU 数, 集群当前没空闲节点</li>
                    <li>Kueue Admission 还没批 — 原因在 Workload events</li>
                  </ul>
                  <Paragraph style={{ marginBottom: 0 }}>
                    <Text strong>查法:</Text> 详情页看 Kueue 详情 (ClusterQueue 容量 + AdmissionCheck)。
                  </Paragraph>
                </>
              ),
            },
            {
              key: '2',
              label: 'Q · 训练任务跑完一会儿又重启, 反复无限重启?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  最常见原因: 启动命令里没有 <code>hyperpodrun</code>。HyperPodPyTorchJob operator
                  的"完成"判定只认 Pod 内 :8080 的 HyperPodElasticAgent 上报 (由 hyperpodrun 启动)。
                  裸命令 (如纯 sleep / python) 没起 agent, operator 认为"没真正启动", Pod 退出即被
                  restartPolicy=Always 拉起, 无限重启。
                  把命令经 hyperpodrun 启动即可正常完成 (脚本内部调 hyperpodrun, 或
                  <code>hyperpodrun ... --no-python /bin/bash -c '&lt;cmd&gt;'</code> 托管任意命令)。
                </Paragraph>
              ),
            },
            {
              key: '3',
              label: 'Q · 我能调高自己任务的优先级吗?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  不能 — 调优先级是工作空间管理员才有的写权限 (任务总览页)。
                  普通成员看不到该页。联系工作空间管理员或平台管理员。
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>

      <DocSection title="Pod 崩溃 / 调试" subTitle="Troubleshooting">
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: 'Q · Pod 显示 CrashLoopBackOff, 怎么看原因?',
              children: (
                <>
                  <Paragraph style={{ marginBottom: 6 }}>
                    详情页 Pod 表的"原因"列显真因, 常见:
                  </Paragraph>
                  <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
                    <li><b>NVML: Driver Not Loaded</b> — CUDA 镜像调度到了无 GPU 驱动的节点 (如 gpu=0 用了 CUDA 镜像)</li>
                    <li><b>Evicted / ephemeral-storage / inodes</b> — 节点磁盘或 inode 满, Pod 被驱逐</li>
                    <li><b>Unrecognized model</b> — sglang --model-path 指向的目录不是合法模型</li>
                    <li><b>OOMKilled (exit 137)</b> — 内存超限</li>
                  </ul>
                </>
              ),
            },
            {
              key: '2',
              label: 'Q · 训练 GPU 利用率显示很低 (如 25%), 但我的卡明明满载?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  已修。旧版 GPU 利用率按节点聚合, 碎片调度下 (一节点多卡分给多任务)
                  会把同节点闲置/别任务的卡算进分母, 稀释你的利用率。现按 pod 维度过滤,
                  分母只算你任务实际用的卡, 利用率回正。
                </Paragraph>
              ),
            },
            {
              key: '3',
              label: 'Q · 想进 Pod 调试怎么办?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  训练详情页 Pod 行有"终端"按钮, 浏览器内进 Pod 交互终端。
                  开发机走"连接"按钮 (SSH / VS Code Remote-SSH / SSM)。
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>

      <DocSection title="存储 (FSx / S3)" subTitle="Storage">
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: 'Q · 容器里看不到我的数据集 / 模型?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  检查工作空间是否挂载了对应 FSx/S3 (工作空间详情页存储 Tab)。
                  注意挂载点 = 授权的 mount_path, 模型/数据子路径在启动命令里自己写。
                  每工作空间 FSx 子目录隔离, 看不到别团队数据是设计目标。
                </Paragraph>
              ),
            },
            {
              key: '2',
              label: 'Q · SGLang 推理报 model_path 找不到模型?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  FSx 与 S3 的 --model-path 规则不同: FSx 挂整层, model-path = 挂载点 + 模型子路径;
                  S3 prefetch 把 modelLocation 内容拉到挂载点根, model-path 写挂载点本身 (不带子路径)。
                  填错会报 Unrecognized model / 找不到 config.json。
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>

      <DocSection title="权限 / 登录" subTitle="Auth">
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: 'Q · 登录后看不到任何工作空间?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  你还没被加入任何工作空间 — 找项目负责人 / 平台管理员拉你进去。
                  平台不允许成员自己创建工作空间。
                </Paragraph>
              ),
            },
            {
              key: '2',
              label: 'Q · API Token 怎么拿?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  顶部"获取 API Token"入口生成 — 用于 CI / 脚本场景。
                  过期时间可设 (也可设为永不过期), 按需配置。
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>
    </DocPage>
  );
}
