import { Typography } from 'antd';
import DocPage, {
  DocSection,
  UserBlock,
} from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsDevInstance() {
  return (
    <DocPage
      title="Dev Instance · Docs"
      description="A cloud development environment: pick a template and it is ready to use, with GPUs, a preinstalled ML environment, and the team's shared disks; open Jupyter / Code Editor right in the browser."
      meta={<Text type="secondary">v3 · 2026-06-25</Text>}
    >
      <DocSection title="What It Is" subTitle="What it is" marginTop={0}>
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            A dev instance is an on-demand cloud development machine with GPUs, a preinstalled ML development environment (Python, deep learning
            frameworks, and so on), and the Workspace's shared data disks. Choose either interface: <b>Jupyter</b> or{' '}
            <b>Code Editor (VS Code)</b>.
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>No configuration files to write: just choose a resource pool (GPU / CPU) + a resource template.</li>
            <li>You can use a base image prepared by the platform, or enter your own image address (if admins have enabled custom images).</li>
            <li>Stop / start at any time: once stopped, compute is no longer billed, and your code disk (EBS) is kept for the next start.</li>
            <li>You can mount the team shared disks (FSx / S3) you have been granted access to, and read and write datasets, code, and models directly.</li>
            <li>Once it is up, open Jupyter / Code Editor in the browser with one click; access from a local terminal / local VS Code is also supported.</li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="How to Create One" subTitle="Create">
        <UserBlock>
          <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Go to "Dev Instance" in the left menu → click "New dev instance".</li>
            <li>Enter the name, display name, and description.</li>
            <li>Choose the interface template: Jupyter or Code Editor.</li>
            <li>
              Choose the image: use a <b>base image</b> (prepared by the platform, works out of the box), or choose a <b>custom image</b> and enter
              your own image address (only available when admins have enabled custom images for that template).
            </li>
            <li>Choose the resource pool (GPU / CPU) and resource template: the template fills in the GPU / CPU / memory settings automatically, so there is nothing to enter by hand.</li>
            <li>Set the size of your personal code disk (EBS).</li>
            <li>(Optional) Mount team shared disks: select from the FSx / S3 directories you have been granted access to; multiple selections are allowed.</li>
            <li>(Optional) Add environment variables.</li>
            <li>Submit. Once the status changes to Running, you can open and use it.</li>
          </ol>
        </UserBlock>
      </DocSection>

      <DocSection title="How to Connect" subTitle="Connect">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            Once the dev instance is running, the details page has two entry points:
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>"Open JupyterLab" / "Open Code Editor"</b>: the most common. Opens the development interface in a new browser tab,
              with no local installation or configuration; click it and start writing code and running notebooks.
            </li>
            <li>
              <b>"Connect"</b>: for people who prefer local tools; opens a dialog with three command-line / local access methods:
              <ul style={{ paddingLeft: 20, marginBottom: 0, marginTop: 4 }}>
                <li><b>Terminal (SSH)</b>: copy one command and enter the dev instance directly from your local terminal</li>
                <li><b>VSCode Remote-SSH</b>: copy a config snippet and connect remotely with your local VS Code</li>
                <li><b>Direct SSM connection</b>: command-line access, suited to troubleshooting</li>
              </ul>
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Stop / Start / Delete" subTitle="Lifecycle">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>
              <b>Stop</b>: stop it when not in use to release the GPUs / compute (it no longer takes up quota); <b>the code disk data is kept</b>.
            </li>
            <li>
              <b>Start</b>: restart a stopped dev instance and pick up where you left off in the previous environment.
            </li>
            <li>
              <b>Delete</b>: fully reclaims the dev instance, deleting its personal code disk along with it (back up important data first).
              Team shared disks (FSx / S3) are not affected.
            </li>
          </ul>
        </UserBlock>
      </DocSection>

      <DocSection title="Status Codes · Troubleshooting Reference" subTitle="Status reference">
        <UserBlock>
          <Paragraph style={{ marginBottom: 6 }}>
            The ? icon in the top-right corner of the list page / details page expands a <b>status guide tip</b> that lists all status values.
            Here is a short reference for troubleshooting (in workflow order):
          </Paragraph>
          <ul style={{ paddingLeft: 20, marginBottom: 6 }}>
            <li><b>(empty)</b> → <b>Initialized</b>: the CR was just created, and the Operator has not done its first reconcile / has taken over</li>
            <li><b>Progressing</b>: Pod being created / pulling the image / attaching EBS / starting the SSM agent / initializing the IDE</li>
            <li><b>Available</b>: the target state; you can click "Connect" or "Open JupyterLab" / "Open Code Editor"</li>
            <li><b>Stopped</b>: stopped by you / reclaimed for being idle; the EBS volume is kept, click "Start" to restore it</li>
            <li><b>Degraded</b>: Pod CrashLoop / node lost / EBS mount failed; check "Status timeline (K8s Conditions)" on the details page to troubleshoot</li>
            <li><b>Queued / Error</b>: states inferred from the Pod (only appear when the details page syncs)</li>
          </ul>
          <Paragraph style={{ marginBottom: 0 }}>
            The list page has two independent filters, <b>Task status</b> (CR phase) and <b>Queue status</b> (Kueue's six states),
            with counts; switching chips shows the current number of matches.
          </Paragraph>
        </UserBlock>
      </DocSection>

      <DocSection title="Security" subTitle="Security">
        <UserBlock>
          <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
            <li>Only you can sign in to your dev instance; nobody else can get in.</li>
            <li>Shared disks are mounted according to grants: you can only access directories you have been granted, and cannot see other teams' data.</li>
            <li>Dev instances run on the internal network and are not exposed directly to the internet.</li>
            <li>Actions such as create / start / stop / delete all leave audit records.</li>
          </ul>
        </UserBlock>
      </DocSection>
    </DocPage>
  );
}
