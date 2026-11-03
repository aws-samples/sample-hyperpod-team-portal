import PptxGenJS from 'pptxgenjs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const SHOTS = join(ROOT, 'screenshots');
const OUT = join(ROOT, 'HyperPod-UI-SOW.pptx');

// Section = 章节分隔；slides 在一个 section 下
const sections = [
  {
    title: '一、算法工程师工作台',
    slides: [
      { file: '01-login.png', title: '登录 · Cognito SSO + Identity Center', note: '企业级登录页；左侧品牌渐变 + 右侧登录卡；预留 Identity Center SSO 切换通道' },
      { file: '02-workspace-list.png', title: '工作空间列表 · 多租户隔离', note: '卡片式配额水位 + 成员头像 + 活跃资源徽章；映射 K8s Namespace 硬隔离' },
      { file: '03-workspace-dashboard.png', title: '工作空间概览', note: 'GPU 利用率 / 活跃任务 / 本月开销 KPI + 最近作业 + 成员活跃度 + 配额详情 + 事件 Timeline' },
      { file: '04-tasks-overview.png', title: '任务总览 · 跨类型聚合', note: '合并开发机 + 训练 + 推理三类任务；算法工程师每天的"首页"；支持类型/状态/时间多维筛选' },
    ],
  },
  {
    title: '二、开发机（DevInstance）',
    slides: [
      { file: '05-dev-list.png', title: '开发机列表', note: 'ProTable 一览实例；状态色 + GPU 规格 + 运行时长 + 一键 IDE/SSH 入口' },
      { file: '14-dev-detail.png', title: '开发机详情 · SSM 一键连接', note: '4 种接入：SSM Port Forwarding / SSH / VSCode Remote / Cursor；命令一键复制；全程私有子网无公网 IP（需求 6.9）' },
    ],
  },
  {
    title: '三、训练任务（TrainingJob）',
    slides: [
      { file: '06-training-list.png', title: '训练任务列表', note: '状态中文化；当前步数/总步数进度条；支持克隆 + 从 Checkpoint 恢复操作' },
      { file: '07-training-create.png', title: '创建训练任务 · 计算资源池 + 配额预览', note: '第一步计算资源池卡片选择 + 底部固定配额预览条；NCCL/EFA 自动注入；Monaco YAML 预览' },
      { file: '15-training-detail-overview.png', title: '训练详情 · 概览', note: '运行时长 / 步数进度 / 当前 Loss / GPU 平均利用率 4 KPI + 任务配置详情' },
      { file: '16-training-detail-monitoring.png', title: '训练监控 · Job / Pod / GPU 三维切换', note: '监控 Tab 嵌入详情页；CPU/MEM/GPU 利用率/显存/SM/网络 6 张折线；时间范围选择器' },
      { file: '17-training-detail-logs.png', title: '训练日志 · 实时 + 历史归档', note: 'RANK 过滤 + 多 Pod 聚合 + tail 模式 + S3 归档查询（需求 3.7 Pod 删除后仍可查）' },
      { file: '18-training-detail-checkpoints.png', title: '检查点管理', note: 'FSx 检查点列表；按 step 排序；支持从任意检查点一键恢复训练' },
    ],
  },
  {
    title: '四、推理服务（InferenceService）',
    slides: [
      { file: '08-inference-list.png', title: '推理服务列表', note: '框架 Badge（vLLM/SGLang/TRT-LLM）+ 模型路径 + QPS/TTFT 关键指标' },
      { file: '09-inference-create.png', title: '创建推理服务 · 引擎结构化参数', note: 'vLLM / SGLang / TRT-LLM 按引擎切换参数集；tp / max_model_len / KV Cache / 量化等结构化字段；Monaco YAML 预览' },
      { file: '19-inference-detail.png', title: '推理服务详情 · 端点信息', note: '自动生成 endpoint URL + 默认 JWT 鉴权 + 扩缩容 + 端点测试 Playground' },
      { file: '19b-inference-llm-monitoring.png', title: 'LLM 指标 Panel · 核心差异化', note: 'TTFT 分位（p50/p99）/ ITL / Token 吞吐 / KV Cache / QPS / 错误率；SLO 红线告警' },
    ],
  },
  {
    title: '五、实验与资产管理',
    slides: [
      { file: '10-experiments.png', title: '实验管理 · ML 原生二级抽象', note: '实验树 + 超参→指标 Parallel Coordinates；final_loss 梯度着色；超参横向对比看出最优组合' },
      { file: '11-models.png', title: '模型仓库', note: '卡片式展示；来源 Badge（训练产物 / HuggingFace / 上传）+ 版本管理 + 一键部署为推理服务' },
      { file: '12-datasets.png', title: '数据集', note: 'FSx 路径注册 + 版本化 + 挂载共享 + 数据来源追溯（S3 / HuggingFace / 本地）' },
      { file: '13-images.png', title: '镜像中心', note: '四 Tab（官方 / 团队 / 个人 / 社区）；ECR 镜像 + 扫描报告 + Dockerfile 预览' },
    ],
  },
  {
    title: '六、基础设施中心（平台管理员）',
    slides: [
      { file: '20-admin-dashboard.png', title: '全局仪表盘', note: '集群 GPU 利用率 / 活跃工作空间 / 在线用户 / 月消耗；Top 工作空间资源占用排行 + 告警流 + 成本趋势' },
      { file: '21-admin-cluster.png', title: '集群管理 · HyperPod + EKS 双视图', note: 'HyperPod Cluster KPI + Instance Group 分布 + 关联 EKS 集群（版本/Addon/Access Entries）+ 7 天健康时间线' },
      { file: '22-admin-resource-pools.png', title: '计算资源池 · 对标 PAI 资源组', note: '通用池 / GPU 加速池 H100 / GPU 加速池 A100 / 专属池；每池绑定 Kueue 队列 + 授权工作空间 + 扩缩容操作' },
      { file: '23-admin-nodes.png', title: '节点管理 · 48 节点实时监控', note: '节点健康状态 + GPU 负载 + 运行 Pod 数 + 下线替换；点击行展示事件时间线 + 温度曲线' },
      { file: '24-admin-scheduling.png', title: '调度队列 · Kueue 视图', note: 'ClusterQueue 容量/占用/排队 + 当前排队任务 + 平均等待时间 + 抢占事件' },
      { file: '25-admin-quota.png', title: '配额中心 · 二维配额分配', note: '工作空间 × 资源池 二维矩阵；单元格显示配额/已用；点击调整配额；顶部切换用量/配额视图' },
      { file: '26-admin-storage.png', title: '存储与权限 · FSx 权限组', note: '3 Tab：FSx 文件系统 / 权限组（按路径授权 uid/gid/mode）/ 挂载审计；对应需求 9 FSx 路径级权限' },
      { file: '27-admin-network.png', title: '网络拓扑 · 全私有子网', note: 'VPC 信息 + 子网分布（Public/Private）+ 安全组 + 15+ VPC Endpoint + NAT Gateway 状态' },
      { file: '28-admin-events.png', title: '运维事件 · 集群事件流', note: '节点故障 + 替换 + 升级任务 + 配额变更 + 抢占事件；按严重等级和时间筛选' },
      { file: '29-admin-audit.png', title: '操作审计 · 合规基线', note: '全量操作日志；操作人 × 角色 × 目标资源 × IP；对标等保三级 / SOC 2 审计要求' },
    ],
  },
];

async function buildFor(mode) {
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'HyperPod UI Platform Team';
  pptx.company = 'HyperPod Platform';
  pptx.title = `HyperPod UI Platform — ${mode === 'light' ? 'Light' : 'Dark'} Theme`;

  // 封面
  const cover = pptx.addSlide();
  cover.background = { color: mode === 'dark' ? '0B0F1A' : 'F5F7FA' };
  cover.addText('HyperPod UI Platform', {
    x: 0.6, y: 2.4, w: 12, h: 1.2,
    fontSize: 48, bold: true, fontFace: 'PingFang SC',
    color: mode === 'dark' ? 'FFFFFF' : '0958D9',
  });
  cover.addText('企业级 ML 基础设施 · 构建于 AWS SageMaker HyperPod on EKS', {
    x: 0.6, y: 3.7, w: 12, h: 0.6,
    fontSize: 22, fontFace: 'PingFang SC',
    color: mode === 'dark' ? 'B0B8C4' : '5A6B80',
  });
  const totalPages = sections.reduce((a, s) => a + s.slides.length, 0);
  cover.addText(`${mode === 'light' ? '亮色主题' : '暗色主题'}  ·  ${totalPages} 核心页面  ·  v2.0 修订方案 + Stage 5 对齐`, {
    x: 0.6, y: 4.5, w: 12, h: 0.5,
    fontSize: 16, fontFace: 'PingFang SC',
    color: mode === 'dark' ? '7A86A0' : '8C97A8',
  });
  cover.addText('SOW 视觉交付稿 · 2026-04-19', {
    x: 0.6, y: 6.5, w: 12, h: 0.4,
    fontSize: 12, fontFace: 'PingFang SC',
    color: mode === 'dark' ? '5A6B80' : 'A8B3C2',
  });

  let missing = 0;
  let pageNum = 1;

  for (const section of sections) {
    // 章节扉页
    const divider = pptx.addSlide();
    divider.background = { color: mode === 'dark' ? '0F1520' : 'EFF4FA' };
    divider.addText(section.title, {
      x: 0.6, y: 3.0, w: 12, h: 1.2,
      fontSize: 40, bold: true, fontFace: 'PingFang SC',
      color: mode === 'dark' ? 'FFFFFF' : '0958D9',
    });
    divider.addText(`${section.slides.length} 个页面`, {
      x: 0.6, y: 4.2, w: 12, h: 0.5,
      fontSize: 16, fontFace: 'PingFang SC',
      color: mode === 'dark' ? '8C97A8' : '5A6B80',
    });

    for (const s of section.slides) {
      const imgPath = join(SHOTS, mode, s.file);
      if (!existsSync(imgPath)) {
        console.log(`  ! missing ${mode}/${s.file}`);
        missing++;
        continue;
      }
      pageNum++;
      const slide = pptx.addSlide();
      slide.background = { color: mode === 'dark' ? '0B0F1A' : 'FFFFFF' };
      slide.addText(s.title, {
        x: 0.4, y: 0.2, w: 12.5, h: 0.5,
        fontSize: 20, bold: true, fontFace: 'PingFang SC',
        color: mode === 'dark' ? 'FFFFFF' : '0958D9',
      });
      slide.addText(s.note, {
        x: 0.4, y: 0.7, w: 12.5, h: 0.35,
        fontSize: 11, fontFace: 'PingFang SC',
        color: mode === 'dark' ? '8C97A8' : '5A6B80',
      });
      slide.addImage({
        path: imgPath,
        x: 0.4, y: 1.1, w: 12.5, h: 6.2,
        sizing: { type: 'contain', w: 12.5, h: 6.2 },
      });
      // 页码
      slide.addText(`${section.title.split('、')[0]} / ${pageNum}`, {
        x: 11.5, y: 7.15, w: 1.5, h: 0.3,
        fontSize: 9, fontFace: 'PingFang SC', align: 'right',
        color: mode === 'dark' ? '5A6B80' : 'A8B3C2',
      });
    }
  }

  const outFile = OUT.replace('.pptx', `-${mode}.pptx`);
  await pptx.writeFile({ fileName: outFile });
  console.log(`  ✓ ${outFile}${missing ? ` (missing ${missing})` : ''}`);
  return outFile;
}

async function run() {
  console.log('Building PPTX...');
  const light = await buildFor('light');
  const dark = await buildFor('dark');
  console.log('\nDone.');
  console.log(`  Light: ${light}`);
  console.log(`  Dark:  ${dark}`);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
