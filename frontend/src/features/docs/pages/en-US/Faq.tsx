import { Collapse, Typography } from 'antd';
import DocPage, { DocSection } from '../../components/DocPage';

const { Paragraph, Text } = Typography;

export default function DocsFaq() {
  return (
    <DocPage
      title="FAQ · Docs"
      description='Common pitfalls when running training / inference / dev instances, written as "symptom → cause → action".'
      meta={<Text type="secondary">v2 · 2026-06-23</Text>}
    >
      <DocSection title="Task Queuing / Status" subTitle="Queuing" marginTop={0}>
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: 'Q · My training job stays Pending. What is going on?',
              children: (
                <>
                  <Paragraph style={{ marginBottom: 6 }}>
                    <Text strong>Possible causes:</Text>
                  </Paragraph>
                  <ul style={{ paddingLeft: 20 }}>
                    <li>The Workspace quota is used up: other tasks are holding the GPUs, so there are none left for you</li>
                    <li>The cluster currently has no free nodes for the number of GPUs the selected resource template requires</li>
                    <li>Kueue Admission has not admitted it yet: the reason is in the Workload events</li>
                  </ul>
                  <Paragraph style={{ marginBottom: 0 }}>
                    <Text strong>How to check:</Text> On the details page, open "Kueue details" (ClusterQueue capacity + AdmissionCheck).
                  </Paragraph>
                </>
              ),
            },
            {
              key: '2',
              label: 'Q · My training job finishes, then restarts shortly afterwards, over and over?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  The most common cause: the launch command does not include <code>hyperpodrun</code>. The HyperPodPyTorchJob operator
                  only treats a job as "completed" based on reports from the HyperPodElasticAgent on :8080 inside the Pod (started by hyperpodrun).
                  A bare command (e.g. plain sleep / python) does not start the agent, so the operator considers the job "never really started", and as soon as the Pod exits,
                  restartPolicy=Always brings it back up, restarting it endlessly.
                  Launch the command through hyperpodrun and the job completes normally (call hyperpodrun inside the script,
                  or use <code>hyperpodrun ... --no-python /bin/bash -c '&lt;cmd&gt;'</code> to wrap any command).
                </Paragraph>
              ),
            },
            {
              key: '3',
              label: 'Q · Can I raise the priority of my own task?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  No. Changing priority is a write permission that only Workspace admins have (the Task Overview page).
                  Regular members cannot see that page. Contact your Workspace admin or a platform admin.
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>

      <DocSection title="Pod Crashes / Debugging" subTitle="Troubleshooting">
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: 'Q · A Pod shows CrashLoopBackOff. How do I find out why?',
              children: (
                <>
                  <Paragraph style={{ marginBottom: 6 }}>
                    The "Reason" column of the Pod table on the details page shows the real cause. Common ones:
                  </Paragraph>
                  <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
                    <li><b>NVML: Driver Not Loaded</b>: a CUDA image was scheduled onto a node without a GPU driver (e.g. a CUDA image used with gpu=0)</li>
                    <li><b>Evicted / ephemeral-storage / inodes</b>: the node's disk or inodes are full, so the Pod was evicted</li>
                    <li><b>Unrecognized model</b>: the directory that sglang --model-path points to is not a valid model</li>
                    <li><b>OOMKilled (exit 137)</b>: the memory limit was exceeded</li>
                  </ul>
                </>
              ),
            },
            {
              key: '2',
              label: 'Q · Training GPU utilization shows very low (e.g. 25%), but my GPUs are clearly fully loaded?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  Fixed. GPU utilization used to be aggregated per node, so under fragmented scheduling (the GPUs on one node split across multiple tasks),
                  idle GPUs and other tasks' GPUs on the same node were counted in the denominator, diluting your utilization. It is now filtered by pod,
                  so the denominator only counts the GPUs your task actually uses, and utilization is accurate again.
                </Paragraph>
              ),
            },
            {
              key: '3',
              label: 'Q · How do I get into a Pod to debug?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  On the training details page, each Pod row has a "Terminal" button that opens an interactive terminal in the Pod right in the browser.
                  For dev instances, use the "Connect" button (SSH / VSCode Remote-SSH / SSM).
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>

      <DocSection title="Storage (FSx / S3)" subTitle="Storage">
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: "Q · I can't see my dataset / model inside the container?",
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  Check whether the Workspace has the corresponding FSx/S3 mounted (the "FSx Mounts" / "S3 Mounts" tabs on the Workspace details page).
                  Note that the mount point = the authorized mount_path; you write the model/data subpath in the launch command yourself.
                  Each Workspace's FSx is isolated by subdirectory, and not being able to see other teams' data is by design.
                </Paragraph>
              ),
            },
            {
              key: '2',
              label: 'Q · SGLang inference reports that model_path cannot find the model?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  FSx and S3 follow different --model-path rules: FSx mounts the whole tree, so model-path = mount point + model subpath;
                  S3 prefetch pulls the contents of modelLocation into the root of the mount point, so model-path is the mount point itself (no subpath).
                  Getting it wrong produces Unrecognized model / config.json not found.
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>

      <DocSection title="Permissions / Sign-In" subTitle="Auth">
        <Collapse
          accordion
          bordered={false}
          style={{ background: 'transparent' }}
          items={[
            {
              key: '1',
              label: "Q · I can't see any Workspace after signing in?",
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  You have not been added to any Workspace yet: ask your project lead / a platform admin to add you.
                  The platform does not allow members to create Workspaces themselves.
                </Paragraph>
              ),
            },
            {
              key: '2',
              label: 'Q · How do I get an API token?',
              children: (
                <Paragraph style={{ marginBottom: 0 }}>
                  Generate one from the "API Token" entry at the top of the page; it is meant for CI / scripting scenarios.
                  You can set an expiration time (or make it never expire), as needed.
                </Paragraph>
              ),
            },
          ]}
        />
      </DocSection>
    </DocPage>
  );
}
