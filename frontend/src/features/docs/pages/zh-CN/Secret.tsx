import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsSecret() {
  return (
    <DocPage
      title="Token 中心 · 文档"
      description="个人 kv Secret — 保存 GitHub / HuggingFace / API key 等敏感值, 训练任务按环境变量注入。"
      meta={<Text type="secondary">v1 · 2026-07-20</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            每个用户在<b>每个工作空间</b>各有一把私人 Secret, 装若干 key-value 对。
            用途:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>拉私有 git repo — 存 <code>GITHUB_TOKEN</code>, 训练启动脚本读环境变量 <code>$GITHUB_TOKEN</code></li>
            <li>下 HuggingFace 私有模型 — 存 <code>HF_TOKEN</code></li>
            <li>调外部 API — 存自己的 API key</li>
          </ul>
          <Paragraph style={{ marginBottom: 0, marginTop: 8 }}>
            <b>关键</b>: value 保存后<b>不回显</b> (像 GitHub PAT), 列表只显 key 名。
            <b>不同用户互相看不见 key</b> — 你只能管自己的。
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>底层 K8s Secret 名 = <code>&lt;owner-username&gt;-secrets</code>, 平台自动派生, 用户无感</li>
            <li>训练 CR 渲染时: env_secrets → <code>valueFrom.secretKeyRef</code> (值不进 CR 明文)</li>
            <li>DDB 里只登记 keys 列表, value 只在 K8s Secret 里</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="怎么用" subTitle="How to use">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Step 1</b> — Token 中心 → "新建 key" → 填 key 名 (= 环境变量名) + value → 保存。
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Step 2</b> — 创建训练任务时, "环境变量"段选"从 Secret 引用", 挑刚建的 key 名 → 提交。
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            <b>Step 3</b> — 训练启动脚本里像普通环境变量一样读: <code>$GITHUB_TOKEN</code>, <code>echo $HF_TOKEN</code>。
          </Paragraph>
        </UserBlock>
      </DocSection>

      <DocSection title="约束与限制" subTitle="Constraints">
        <KeyValueList
          items={[
            { k: 'key 命名', v: '大写字母 + 数字 + 下划线 (K8s env var 命名规范), 例 GITHUB_TOKEN' },
            { k: 'value 大小', v: '单条 ≤ 1MB (K8s Secret 硬上限 1MB, 平台建议 &lt; 64KB)' },
            { k: '重复', v: '同 key 覆盖式更新 (PUT 语义), 无版本历史' },
            { k: '删除', v: '幂等; 删的时候如果有跑中的任务在用, 任务继续用旧值, 新任务读不到' },
            { k: '共享', v: '只能自己用; 无跨用户共享 (需要共享改用 ws admin 挂 SA 环境变量)' },
          ]}
        />
      </DocSection>

      <DocSection title="个人 API Token" subTitle="Personal API Token">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            另一类"Token" — CLI / 脚本调平台自身 API 时用, 免 Cognito 登录。
            管理入口在 <b>右上角用户菜单 → API Token</b> (不在 Token 中心里)。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>建 token → 一次性显示明文 (只显一次, 复制走)</li>
            <li>用: <code>curl -H "Authorization: Bearer &lt;token&gt;" https://.../api/v1/...</code></li>
            <li>Token 权限 = 你本人权限, 不能提权</li>
            <li>可撤销 (revoke), DDB 里落 <code>ApiTokens</code> 表, hash 后存</li>
          </ul>
        </UserBlock>
        <TechBlock>
          Token = base64(random 32B), 显示 = <code>pltk_&lt;random&gt;</code>; 存 hash (sha256).
          验证走 <code>app/core/auth_middleware.py</code>: 先尝试 Cognito JWT 失败再尝试 ApiToken 匹配 hash.
        </TechBlock>
      </DocSection>

      <DocSection title="尚未实现" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Secret 版本历史 / 回滚</li>
            <li>ws 共享 Secret (所有成员共用一把)</li>
            <li>Token 细粒度权限 (当前 token=本人全权)</li>
            <li>OIDC token exchange (SDK 拿 Cognito token 换平台 token)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
