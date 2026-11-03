import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsRegistry() {
  return (
    <DocPage
      title="镜像中心 · 文档"
      description="工作空间级镜像目录 + Dockerfile 在线构建 (CodeBuild) — 三类任务复用, 按用途标签选。"
      meta={<Text type="secondary">v1.1 · 2026-07-27</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            每个工作空间维护一份"可用镜像清单", 创建任务 (开发机 / 训练 / 推理) 时不再手填 URI —
            从清单里按用途 tag 选。清单条目两种来源:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>注册已有 ECR 镜像</b> — 从 ECR 已 push 的镜像里挑一个, 打上用途标签 (dev/training/inference)</li>
            <li><b>在线构建</b> — 提交 Dockerfile → 后端建 CodeBuild 项目 → 构建成功自动 push ECR + 自动注册进清单</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>DDB 表: <code>WorkspaceImages</code> (清单) + <code>ImageBuilds</code> (构建历史)</li>
            <li>构建后端: AWS CodeBuild (project 名由 <code>CODEBUILD_PROJECT_NAME</code> env 指定)</li>
            <li>构建产物: 推送到本 ws 对应 ECR repo, tag = 用户填的 target_tag</li>
            <li>构建 context: Dockerfile 直接文本传后端 → 打 zip → S3 上传 → CodeBuild 拉取</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="清单 · 注册已有镜像" subTitle="Register from ECR">
        <UserBlock>
          镜像中心 → "注册" → 从 ECR 私有仓库 dropdown 选镜像 + tag → 打显示名 + 用途标签 (可多选) → 确认。
          <br />
          <br />
          用途标签决定了这个镜像在哪个"创建表单"里出现:
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><code>dev</code> → 开发机镜像 dropdown</li>
            <li><code>training</code> → 训练任务镜像 dropdown</li>
            <li><code>inference</code> → 推理服务镜像 dropdown (含 llm-d)</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="在线构建" subTitle="Online build">
        <UserBlock>
          镜像中心 → "在线构建" → 粘 Dockerfile 内容 + 填 target_tag + 用途标签 + 选算力档 (SMALL / MEDIUM / LARGE / 2XLARGE) → 提交。
          <br />
          <br />
          <b>target_tag 格式</b>: <code>namespace/repo-name:v1</code>
          — 冒号左侧是 <b>ECR repo 原文</b> (2026-07-24 起平台不再加 <code>hp-</code> 前缀,
          由使用者自定命名); repo 段须符合 ECR 规范:
          小写字母/数字开头, <code>.</code>{' '}<code>_</code>{' '}<code>-</code> 单字符分隔,
          <code>/</code> 分路径, 不允许大写/连续分隔符/首尾分隔符。例:
          <code>my-team/bert:v1</code> ✓ · <code>My-Img</code> ✗
          <br />
          <br />
          "构建历史" tab 看进度:
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>building</b> — CodeBuild 跑中, 可点"日志"看 CodeWatch 实时 output</li>
            <li><b>success</b> — 已 push ECR 并自动注册到镜像清单</li>
            <li><b>failed</b> — 报错, 看日志排查; 不会自动注册</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: '提交', v: 'POST /workspaces/{ws}/image-builds — body: dockerfile + target_tag + uses[] + compute_type' },
              { k: '轮询', v: 'GET /workspaces/{ws}/image-builds — 5s 轮询状态' },
              { k: '看日志', v: 'GET /workspaces/{ws}/image-builds/{id}/logs — 拉 CodeBuild log stream 文本' },
              { k: '底层', v: 'CodeBuild 提交 → 用官方 kaniko / docker image 构建 → docker push → 后端 hook 自动注册镜像' },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="ECR 只读浏览" subTitle="Browse ECR">
        <TechBlock>
          创建任务表单里的镜像 dropdown 是从 <code>/registry/ecr/repos</code> 和 <code>/registry/ecr/repos/{'{'}name{'}'}/tags</code> 拉的
          — 平台账号 ECR 的直接只读浏览, 与"工作空间镜像清单"是两回事:
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>ECR dropdown</b> — 平台账号 ECR 里所有 repo/tag, 全 ws 共用</li>
            <li><b>工作空间清单</b> — ws admin 挑选后打标签, 有权限隔离 + 用途分类</li>
          </ul>
          创建表单支持两种来源: 走清单 (推荐, 有分类) 或直接填 ECR URI (兼容)。
        </TechBlock>
      </DocSection>

      <DocSection title="权限" subTitle="Permissions">
        <KeyValueList
          items={[
            { k: '注册镜像', v: 'ws 成员均可 (提交后 creator 落自己 username)' },
            { k: '在线构建', v: 'ws 成员均可 (计费落到 ws 层)' },
            { k: '删除镜像', v: 'creator 本人或 ws admin (删镜像不删 ECR 里的 image, 只清清单条目)' },
            { k: 'ECR dropdown', v: '任何登录用户可读 (平台账号内)' },
          ]}
        />
      </DocSection>

      <DocSection title="尚未实现" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Dockerfile 直接上传 (当前只有文本粘贴)</li>
            <li>私有 base image / 私仓凭证透传 CodeBuild (regcred secret)</li>
            <li>镜像漏洞扫描结果展示 (ECR scan 已开, UI 未接入)</li>
            <li>多 arch (arm64) 并行构建</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
