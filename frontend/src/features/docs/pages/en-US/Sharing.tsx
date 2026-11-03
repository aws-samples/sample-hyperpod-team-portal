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
      title="Sharing · Docs"
      description="Share your dev instances / training jobs with other members of the same Workspace in one click; shared items are visible read-only."
      meta={<Text type="secondary">v1 · 2026-07-20</Text>}
    >
      <DocSection title="What It Is" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            By default, a list only shows the tasks you created (<code>scope=mine</code>). Once you share a task, the people you shared it with also see it in their own lists
            (marked "from &lt;creator&gt;") and can view its details, status, logs, and metrics, <b>read-only: they cannot change or delete it</b>.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Entry point: details page / list page actions column → "Share" → select one or more members of the same Workspace in the dialog</li>
            <li>Only the resource's <b>creator</b> sees the sharing entry point (you cannot share on someone else's behalf)</li>
            <li>Share targets must be <b>members of the same Workspace</b>; sharing across Workspaces is not supported</li>
            <li>Sharing is additive and can be removed at any time</li>
          </ul>
        </UserBlock>
        <TechBlock>
          Supported resource types: dev instance (<code>dev</code>) / training (<code>train</code>); inference / llm-d are not wired up yet
          (planned for the second batch). The data lives in the DDB <code>ResourceShares</code> table, and when a list page uses scope=mine, the rows shared with you are merged in.
          <br />
          Deleting the source resource cascades to delete all of its share records (<code>test_cascade_delete.py</code>).
        </TechBlock>
      </DocSection>

      <DocSection title="Permission Matrix" subTitle="Permissions">
        <KeyValueList
          items={[
            { k: 'Creator', v: 'Full permissions: create/delete/edit · share · remove others' },
            { k: 'Share recipient', v: 'Read-only: view details / logs / monitoring; cannot stop/delete/edit · cannot reshare' },
            { k: 'Workspace member (not shared with)', v: 'Not visible (the scope=mine list does not return it)' },
            { k: 'Workspace admin', v: 'scope=all shows all tasks in the Workspace (not through sharing)' },
            { k: 'Platform admin', v: 'scope=all shows everything platform-wide (not through sharing)' },
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
                    body: <code>{'{ res_type, res_id, target_usernames[] }'}</code> (idempotent; duplicate shares are skipped)
                  </>
                ),
              },
              {
                k: 'GET /workspaces/{ws}/shares/{res_type}/{res_id}',
                v: 'Lists who it has been shared with (only the creator can query this)',
              },
              {
                k: 'DELETE /workspaces/{ws}/shares/{res_type}/{res_id}/users/{username}',
                v: 'Removes sharing for one person (only the creator can do this); idempotent',
              },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="FAQ" subTitle="FAQ">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>Can't find the person you want to share with in the dropdown?</b> First add them to the Workspace in the "Members" tab of the Workspace details page,
              since sharing only supports members within the Workspace.
            </li>
            <li>
              <b>Can recipients see logs / monitoring?</b> Yes. All read-only endpoints are allowed (details / logs / monitoring / status-detail).
            </li>
            <li>
              <b>What happens if a recipient leaves the Workspace?</b> Platform-level member removal cascades to clean up all share records in that Workspace that have them
              as the target.
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Not Yet Implemented" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Inference / llm-d resource types (second batch; currently only dev / train)</li>
            <li>"Share with the whole Workspace" / group sharing (you can only add people one by one)</li>
            <li>Elevating recipients to write permission (planned; pending design review)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
