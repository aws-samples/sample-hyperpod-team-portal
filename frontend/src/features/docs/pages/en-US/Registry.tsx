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
      title="Image Hub · Docs"
      description="A Workspace-level image catalog + online Dockerfile builds (CodeBuild), reused by all three task types and picked by purpose tag."
      meta={<Text type="secondary">v1.1 · 2026-07-27</Text>}
    >
      <DocSection title="What It Is" subTitle="Concept" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Each Workspace maintains a list of "available images", so when you create a task (dev instance / training / inference)
            you no longer type the URI by hand: you pick one from the list by purpose tag. List entries come from two sources:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>Register an existing ECR image</b>: pick an image that has already been pushed to ECR and give it purpose tags (dev/training/inference)</li>
            <li><b>Online build</b>: submit a Dockerfile → the backend creates a CodeBuild project → when the build succeeds, the image is pushed to ECR + registered in the list automatically</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>DDB tables: <code>WorkspaceImages</code> (list) + <code>ImageBuilds</code> (build history)</li>
            <li>Build backend: AWS CodeBuild (the project name is set by the <code>CODEBUILD_PROJECT_NAME</code> env var)</li>
            <li>Build output: pushed to the ECR repo of this Workspace, with tag = the target_tag the user entered</li>
            <li>Build context: the Dockerfile is sent to the backend as text → zipped → uploaded to S3 → pulled by CodeBuild</li>
          </ul>
        </TechBlock>
      </DocSection>

      <DocSection title="Image List · Register an Existing Image" subTitle="Register from ECR">
        <UserBlock>
          Image Hub → "Register image" → pick an image + tag from the private ECR repository dropdown → enter a display name + purpose tags (multiple allowed) → confirm.
          <br />
          <br />
          The purpose tags decide which "create form" the image appears in:
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><code>dev</code> → the dev instance image dropdown</li>
            <li><code>training</code> → the training job image dropdown</li>
            <li><code>inference</code> → the inference service image dropdown (including llm-d)</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Online Build" subTitle="Online build">
        <UserBlock>
          Image Hub → "Build image" → paste the Dockerfile content + enter the target_tag + purpose tags + choose a build spec tier (SMALL / MEDIUM / LARGE / 2XLARGE) → submit.
          <br />
          <br />
          <b>target_tag format</b>: <code>namespace/repo-name:v1</code>. The part
          to the left of the colon is the <b>ECR repo name, used as-is</b> (since 2026-07-24 the platform no longer adds an <code>hp-</code> prefix,
          so you choose the name yourself); the repo segment must follow ECR naming rules:
          it starts with a lowercase letter or digit, uses single <code>.</code>{' '}<code>_</code>{' '}<code>-</code> characters as separators,
          and uses <code>/</code> for paths; uppercase letters, consecutive separators, and leading/trailing separators are not allowed.
          Examples: <code>my-team/bert:v1</code> ✓ · <code>My-Img</code> ✗
          <br />
          <br />
          Track progress in the "Build History" tab:
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li><b>Building</b>: CodeBuild is running; click "Logs" to see the live CloudWatch output</li>
            <li><b>Succeeded</b>: pushed to ECR and registered in the image list automatically</li>
            <li><b>Failed</b>: an error occurred; check the logs to troubleshoot. The image is not registered automatically</li>
          </ul>
        </UserBlock>
        <TechBlock>
          <KeyValueList
            items={[
              { k: 'Submit', v: 'POST /workspaces/{ws}/image-builds (body: dockerfile + target_tag + uses[] + compute_type)' },
              { k: 'Polling', v: 'GET /workspaces/{ws}/image-builds: polls the status every 5s' },
              { k: 'Logs', v: 'GET /workspaces/{ws}/image-builds/{id}/logs: fetches the CodeBuild log stream text' },
              { k: 'Under the hood', v: 'CodeBuild submission → build with the official kaniko / docker image → docker push → a backend hook registers the image automatically' },
            ]}
          />
        </TechBlock>
      </DocSection>

      <DocSection title="Read-Only ECR Browsing" subTitle="Browse ECR">
        <TechBlock>
          The image dropdown in the create-task forms is fetched from <code>/registry/ecr/repos</code> and <code>/registry/ecr/repos/{'{'}name{'}'}/tags</code>. This
          is direct read-only browsing of the platform account's ECR, which is a different thing from the "Workspace image list":
          <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 6 }}>
            <li><b>ECR dropdown</b>: all repos/tags in the platform account's ECR, shared by all Workspaces</li>
            <li><b>Workspace list</b>: picked and tagged by the Workspace admin, with permission isolation + purpose categories</li>
          </ul>
          The create forms support two sources: the list (recommended, categorized) or entering an ECR URI directly (for compatibility).
        </TechBlock>
      </DocSection>

      <DocSection title="Permissions" subTitle="Permissions">
        <KeyValueList
          items={[
            { k: 'Register an image', v: 'Any Workspace member (after submission, creator is set to your own username)' },
            { k: 'Online build', v: 'Any Workspace member (costs are billed at the Workspace level)' },
            { k: 'Unregister an image', v: 'The creator or a Workspace admin (this only removes the list entry; the image in ECR is not deleted)' },
            { k: 'ECR dropdown', v: 'Readable by any signed-in user (within the platform account)' },
          ]}
        />
      </DocSection>

      <DocSection title="Not Yet Implemented" subTitle="Not yet">
        <TechBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Uploading a Dockerfile file directly (currently only pasting text is supported)</li>
            <li>Private base images / passing private registry credentials through to CodeBuild (regcred secret)</li>
            <li>Showing image vulnerability scan results (ECR scanning is enabled, but the UI is not wired up yet)</li>
            <li>Parallel multi-arch (arm64) builds</li>
          </ul>
        </TechBlock>
      </DocSection>
    </DocPage>
  );
}
