# infrastructure · HyperPod 平台 CDK (Python)

CDK app, 只建 **AWS 资源** (DDB / Cognito / IAM / EKS CPU node group / Pod Identity / access entry)。
K8s 侧 (后端/前端 Deployment + Ingress) 走 `deploy/k8s/` manifest, 不在 CDK 里。

完整部署步骤见 [`docs/deployment-guideline.md`](../docs/deployment-guideline.md)。

## 结构

```
infrastructure/
├── app.py                      # CDK app entry
├── cdk.json                    # context (换环境只改这里)
├── requirements.txt
└── stacks/                     # (包名避开 stdlib 'platform')
    ├── platform_stack.py       # 总 Stack, 串所有 Construct + CfnOutput
    ├── ddb_construct.py        # 5 表 + GSI
    ├── cognito_construct.py    # UserPool/Client/Domain
    ├── iam_construct.py        # 4 role (api/pod/ssm/alb-controller)
    ├── nodegroup_construct.py  # CfnNodegroup (2× m5.2xlarge, label role=platform)
    └── eks_access_construct.py # Pod Identity associations + access entry
```

## 常用命令

```bash
cp cdk.json.example cdk.json          # 首次: 从模板建本地 context (cdk.json 已 gitignore, 不入库)
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cdk synth        # 合成检查
cdk deploy       # 部署
cdk destroy      # 删除 (DDB 表 RETAIN, 不会删)
```

## 关键 context (cdk.json)

换环境 (目标集群) 只改 cdk.json: `projectName/account/region/vpcId/privateSubnetIds/eksClusterName/platformFsxFilesystems/ampWorkspaceId` 等。
`platformFsxFilesystems` 是多 FSx 列表, 逗号分隔 `fs-id`; fs-id 直接作 fsx-admin 挂载点 `/fsx-mnt/<fs-id>`, 前端下拉展示名走 AWS `Tags[Name]`。(兼容旧 `fs-id:别名` 格式, 别名段忽略。)
`projectName` 同时作 DDB 表前缀 + 所有资源名前缀 + tag (Project=)。
代码不动。

## 注意

- 包名是 `stacks/` 不是 `platform/` (后者撞 Python 标准库 platform 模块, 会 import 失败)。
- node group / Pod Identity / access entry 用 L1 (Cfn*), 不 import 完整 EKS 集群对象 (避开 HyperPod 底层 EKS import 的坑)。
- access entry 带 `cluster-workspace-admin` group — 后端建带 workspace-default SA 的开发机必需。
- ALB controller IAM policy 现为占位宽 policy, 生产前换官方精确 JSON (见 iam_construct.py 注释)。
