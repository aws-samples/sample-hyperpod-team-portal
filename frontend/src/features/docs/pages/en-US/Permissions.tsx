import { Typography } from 'antd';
import DocPage, { DocSection, KeyValueList } from '../../components/DocPage';

const { Paragraph, Text } = Typography;

/**
 * 关于权限 — 面向最终用户的权限说明 (不讲实现, 只回答"我能做什么 / 为什么按钮没了")。
 *
 * 写作约束:
 *   - 不出现 DDB 表 / gate 函数名 / 401 / 403 / JWT 这类工程术语
 *   - 全篇只用 UserBlock 风格 (DocSection 默认排版), 不用 TechBlock
 *   - 速查表用 KeyValueList, "动作 → 谁能做"两列, 最直观
 */
export default function DocsPermissions() {
  return (
    <DocPage
      title="About Permissions · Docs"
      description="The platform has only three identities. After reading this page you can answer three questions: what can I do, why can't I see a certain button, and who can do it for me."
      meta={<Text type="secondary">v2 · 2026-06-25</Text>}
    >
      <DocSection title="Which Identity You Have" subTitle="Who am I" marginTop={0}>
        <Paragraph style={{ marginBottom: 12 }}>
          The platform has no fine-grained roles, only three identities, ordered by how much they manage, from most to least:
        </Paragraph>
        <KeyValueList
          items={[
            {
              k: 'Platform admin',
              v: (
                <>
                  Manages the whole platform: creates Workspaces and adjusts platform-level switches.
                  There are very few of them, usually colleagues who operate the platform.
                </>
              ),
            },
            {
              k: 'Workspace admin',
              v: (
                <>
                  Manages <b>one particular</b> Workspace: adds members, configures storage, grants access to mounts, views all of the team's tasks, and adjusts task priority.
                  You may be an admin in Workspace A and just a regular member in Workspace B.
                </>
              ),
            },
            {
              k: 'Member',
              v: (
                <>
                  Runs <b>their own</b> dev instances / training jobs / inference services in the Workspaces they belong to.
                  They can only see their own tasks, not other people's.
                </>
              ),
            },
          ]}
        />
        <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
          To find out which identity you currently have, check the dropdown under the avatar in the top-left corner, or look at the left menu: whether it has "Admin Console"
          is the most direct sign (regular members do not see that entry).
        </Paragraph>
      </DocSection>

      <DocSection title="Who Can Do What" subTitle="Capability">
        <Paragraph style={{ marginBottom: 12 }}>
          Below is a quick reference of common actions. The "who" in each row is the people who can do it; everyone else does not see the button in the UI.
        </Paragraph>
        <KeyValueList
          items={[
            { k: 'Create a Workspace', v: <>Only <b>platform admins</b></> },
            { k: 'Delete a Workspace', v: <>Only <b>platform admins</b></> },
            { k: 'Add / remove members', v: <>Only <b>platform admins</b></> },
            {
              k: 'Mount FSx / S3 storage',
              v: <><b>Platform admins</b> or <b>Workspace admins</b></>,
            },
            {
              k: 'Grant members access to a mount',
              v: <><b>Platform admins</b> or <b>Workspace admins</b></>,
            },
            {
              k: 'Maintain resource templates (create / edit / delete)',
              v: (
                <>
                  <b>Platform admins</b> or <b>Workspace admins</b>.
                  Regular members can view but not edit
                </>
              ),
            },
            {
              k: "View all of the team's tasks / adjust task priority",
              v: <><b>Platform admins</b> or <b>Workspace admins</b></>,
            },
            {
              k: 'Create / start / stop / delete your own dev instances · training jobs · inference services',
              v: <><b>Everyone</b> (any Workspace member)</>,
            },
            {
              k: "Stop / delete other people's dev instances / training jobs",
              v: <><b>Platform admins</b> or <b>Workspace admins</b></>,
            },
            {
              k: 'Platform-level switches (priority classes, preemption)',
              v: <>Only <b>platform admins</b></>,
            },
            {
              k: 'Generate your own API token (for scripts / CI)',
              v: <><b>All signed-in users</b> can issue one for themselves</>,
            },
          ]}
        />
      </DocSection>

      <DocSection title="Can't Find a Button? What to Do" subTitle="Where's the button">
        <Paragraph style={{ marginBottom: 12 }}>
          The UI hides entry points based on your identity, so not seeing one usually means "you are not the role responsible for this". Common cases:
        </Paragraph>
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>"I want to create a Workspace, but there is no button"</b>:
            creating Workspaces is a platform admin's job; ask a platform admin or your project lead to create one for you.
          </li>
          <li>
            <b>"I want to add a colleague, but the Members tab has no 'Add member' button"</b>:
            adding members also requires a platform admin; just send them your colleague's username.
          </li>
          <li>
            <b>"I want to see all training jobs in the team, but I can only see my own"</b>:
            this is the regular member view; ask a Workspace admin or platform admin to look,
            or ask them to promote you to Workspace admin.
          </li>
          <li>
            <b>"The disk is not in the mount list when I create a task"</b>:
            mounts require an admin to grant you access individually; ask a Workspace admin to grant you access to that disk (read-only / read-write) in the "FSx Mounts" tab.
          </li>
        </ul>
      </DocSection>

      <DocSection title="Joining · Leaving · Role Changes" subTitle="Lifecycle">
        <Paragraph style={{ marginBottom: 12 }}>
          All "membership changes" take effect immediately; you do not need to sign in again:
        </Paragraph>
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>Joining a Workspace</b>: a platform admin adds you in the "Members" tab of the Workspace details page, and you will see it the next time you refresh.
          </li>
          <li>
            <b>Promotion / demotion</b>: change the "Role" field in the same tab; promotion to Workspace admin or demotion back to regular member takes effect immediately.
          </li>
          <li>
            <b>Removal</b>: also done in the "Members" tab; your <b>running</b> dev instances and training jobs are not stopped automatically,
            but afterwards you can no longer create / modify anything in that Workspace.
          </li>
        </ul>
        <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0, fontSize: 13 }}>
          Being made a platform admin is a high-privilege action; it is not done in the UI but through an offline process run by the platform operators.
        </Paragraph>
      </DocSection>

      <DocSection title="Signing In and Switching Identities" subTitle="Login">
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>You see no Workspaces after signing in</b>: you have not been added to any Workspace yet; ask your project lead or a platform admin to add you.
          </li>
          <li>
            <b>You belong to several Workspaces</b>: switch between them with the Workspace dropdown at the top;
            when you switch to a different Workspace, the left menu and your identity (admin / regular member) change with it.
          </li>
          <li>
            <b>You want to sign in from a script / CI</b>: use the "API Token" entry at the top to generate a token and put it in your script;
            the identity is exactly the same as in your browser (so your script can do exactly what you can do in the UI).
          </li>
          <li>
            <b>Your account or username changed</b>: just sign in again in the browser with the new identity; old API tokens do not expire automatically,
            so if you no longer use one, delete it from the top menu.
          </li>
        </ul>
      </DocSection>

      <DocSection title="Common Misconceptions" subTitle="Pitfalls">
        <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
          <li>
            <b>"I can't see other people's tasks. Is that a bug?"</b> No, it is by design: regular members only see their own;
            to see the whole team's picture, ask an admin to promote you, or ask an admin to take a look.
          </li>
          <li>
            <b>"I'm a platform admin, but a button doesn't show up?"</b> Check the Workspace currently selected at the top of the page;
            if you are still on the Workspace list page, some actions only appear after you select a Workspace.
          </li>
          <li>
            <b>"I'm signed in, so why does an action say 'Insufficient permissions'?"</b> Check whether the avatar in the top-right corner
            shows the username you think it does; after the company switches your SSO account, you must sign in again in the browser once, because old sessions do not switch automatically.
          </li>
          <li>
            <b>"I set a task's priority, but it doesn't seem to take effect?"</b> Adjusting priority is a Workspace admin capability;
            the priority control that regular members see is actually read-only, so ask an admin to adjust it for you.
          </li>
          <li>
            <b>"I removed a colleague from the Workspace, but they are still running tasks?"</b> Removing a member does not automatically stop their running containers;
            if they need to be taken offline immediately, also stop their dev instances / training jobs.
          </li>
        </ul>
      </DocSection>
    </DocPage>
  );
}
