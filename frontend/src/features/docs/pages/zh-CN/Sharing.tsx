import { Typography } from 'antd';
import DocPage, {
  DocSection,
  KeyValueList,
  TechBlock,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsSharing() {
  return (
    <DocPage
      title="资源分享 · 文档"
      description="把自己的开发机 / 训练任务 一键分享给同工作空间的其他成员, 共享只读可见。"
      meta={<Text type="secondary">v1 · 2026-07-20</Text>}
    >
      <DocSection title="它是什么" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            默认列表只显自己创建的任务 (<code>scope=mine</code>)。分享后, 被分享人在自己的列表也能看到这个任务
            (标记"来自 &lt;creator&gt;"), 可以查看详情、状态、日志、指标 — <b>只读, 不能改 / 不能删</b>。
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>入口: 详情页 / 列表页操作栏 → "分享" → 弹窗多选同 ws 成员</li>
            <li>仅资源 <b>creator 本人</b>可见分享入口 (不能替别人分享)</li>
            <li>分享目标必须是 <b>同 ws 成员</b>; 跨 ws 分享不支持</li>
            <li>分享是加法, 可以随时移除</li>
          </ul>
        </UserBlock>
        <TechBlock>
          支持资源类型: 开发机 (<code>dev</code>) / 训练 (<code>train</code>) — 推理 / llm-d 暂未接入
          (第二批规划)。数据落 DDB <code>ResourceShares</code> 表, 列表页 scope=mine 时并入分享给我的行。
          <br />
          删源资源时级联删所有 share 记录 (<code>test_cascade_delete.py</code>)。
        </TechBlock>
      </DocSection>

      <DocSection title="权限矩阵" subTitle="Permissions">
        <KeyValueList
          items={[
            { k: 'creator', v: '完全权限 — 增删改 · 分享 · 移除他人' },
            { k: '被分享人', v: '只读 — 看详情 / 日志 / 监控; 不能停/删/改 · 不能再分享' },
            { k: '同 ws 成员 (未被分享)', v: '不可见 (列表 scope=mine 不返)' },
            { k: 'ws 管理员', v: 'scope=all 可看全 ws 任务 (不通过分享)' },
            { k: '超管', v: 'scope=all 全平台可见 (不通过分享)' },
          ]}
        />
      </DocSection>

      <DocSection title="API" subTitle="Endpoints">
        <TechBlock>
          <KeyValueList
            items={[
              {
                k: 'POST /workspaces/{ws}/shares',
                v: (
                  <>
                    body: <code>{'{ res_type, res_id, target_usernames[] }'}</code> — 幂等, 重复分享跳过
                  </>
                ),
              },
              {
                k: 'GET /workspaces/{ws}/shares/{res_type}/{res_id}',
                v: '列已分享给谁 (仅 creator 可查)',
              },
              {
                k: 'DELETE /workspaces/{ws}/shares/{res_type}/{res_id}/users/{username}',
                v: '移除某人分享 (仅 creator 可操作), 幂等',
              },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="常见问题" subTitle="FAQ">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>分享给的人在下拉里找不到?</b> 先去 ws 成员管理页把这个人加进工作空间 —
              分享只支持 ws 内成员。
            </li>
            <li>
              <b>被分享人能看日志 / 监控吗?</b> 能。所有只读接口都放行 (详情 / logs / monitoring / status-detail)。
            </li>
            <li>
              <b>被分享人退出 ws 会怎样?</b> 平台级的成员移除会级联清理该 ws 里所有以他为
              target 的 share 记录。
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="尚未实现" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>推理 / llm-d 资源类型 (第二批, 当前只有 dev / train)</li>
            <li>"分享全 ws" / group 分享 (只能一个个加人)</li>
            <li>被分享人写权限提升 (planned; 待设计评审)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
