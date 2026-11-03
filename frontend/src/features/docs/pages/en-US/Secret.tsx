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
      title="Token Center · Docs"
      description="Personal kv Secrets: store sensitive values such as GitHub / HuggingFace tokens and API keys, injected into training jobs as environment variables."
      meta={<Text type="secondary">v1 · 2026-07-20</Text>}
    >
      <DocSection title="What It Is" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Each user has one private Secret <b>in each Workspace</b>, holding any number of key-value pairs.
            Use cases:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Pulling a private git repo: store <code>GITHUB_TOKEN</code>, and the training launch script reads the environment variable <code>$GITHUB_TOKEN</code></li>
            <li>Downloading a private HuggingFace model: store <code>HF_TOKEN</code></li>
            <li>Calling an external API: store your own API key</li>
          </ul>
          <Paragraph style={{ marginBottom: 0, marginTop: 8 }}>
            <b>Key point</b>: once a value is saved, it is <b>never shown again</b> (like a GitHub PAT); the list only shows key names. <b>Users
            cannot see each other's keys</b>: you can only manage your own.
          </Paragraph>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>The underlying K8s Secret name = <code>&lt;owner-username&gt;-secrets</code>, derived automatically by the platform and invisible to users</li>
            <li>When the training CR is rendered: env_secrets → <code>valueFrom.secretKeyRef</code> (values never appear in the CR in plain text)</li>
            <li>DDB only records the list of keys; values live only in the K8s Secret</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="How to Use It" subTitle="How to use">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Step 1</b>: Secret Management → "Add key-value" → enter the key name (= environment variable name) + value → save.
          </Paragraph>
          <Paragraph style={{ marginBottom: 6 }}>
            <b>Step 2</b>: When creating a training job, click "Add environment variable from Secret" in the environment variables section, pick the key you just created → submit.
          </Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>
            <b>Step 3</b>: In the training launch script, read it like any other environment variable: <code>$GITHUB_TOKEN</code>, <code>echo $HF_TOKEN</code>.
          </Paragraph>
        </UserBlock>
      </DocSection>

      <DocSection title="Constraints and Limits" subTitle="Constraints">
        <KeyValueList
          items={[
            { k: 'Key naming', v: 'Uppercase letters + digits + underscores (K8s env var naming rules), e.g. GITHUB_TOKEN' },
            { k: 'Value size', v: '≤ 1MB per entry (the K8s Secret hard limit is 1MB; the platform recommends < 64KB)' },
            { k: 'Duplicates', v: 'Writing the same key overwrites it (PUT semantics); there is no version history' },
            { k: 'Deletion', v: 'Idempotent; if a running task is using the key when you delete it, the task keeps using the old value, but new tasks cannot read it' },
            { k: 'Sharing', v: 'For your own use only; there is no cross-user sharing (if you need to share, have a Workspace admin set the environment variables on the SA instead)' },
          ]}
        />
      </DocSection>

      <DocSection title="Personal API Token" subTitle="Personal API Token">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Another kind of "token", used when CLIs / scripts call the platform's own API, so they can skip Cognito sign-in.
            It is managed from <b>the top-right corner → API Token</b> (not on the Secret Management page).
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Generate a token → its plain text is shown once (only once, so copy it right away)</li>
            <li>Usage: <code>curl -H "Authorization: Bearer &lt;token&gt;" https://.../api/v1/...</code></li>
            <li>Token permissions = your own permissions; a token cannot escalate privileges</li>
            <li>Revocable at any time (delete the token to revoke it); stored in the DDB <code>ApiTokens</code> table as a hash</li>
          </ul>
        </UserBlock>
        <TechBlock>
          Token = base64(random 32B), displayed as <code>pltk_&lt;random&gt;</code>; a hash (sha256) is stored.
          Verification goes through <code>app/core/auth_middleware.py</code>: it first tries the Cognito JWT, and if that fails, tries matching the ApiToken hash.
        </TechBlock>
      </DocSection>

      <DocSection title="Not Yet Implemented" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Secret version history / rollback</li>
            <li>Workspace-shared Secrets (one Secret shared by all members)</li>
            <li>Fine-grained token permissions (currently a token = your full permissions)</li>
            <li>OIDC token exchange (the SDK exchanges a Cognito token for a platform token)</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
