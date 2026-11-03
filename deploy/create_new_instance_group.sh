#!/usr/bin/env bash

SUBNET_ID="subnet-0123456789abcdef0"
SOURCE_IG_NAME="cpu-4x"
HYPERPOD_CLUSTER_NAME="0714-hp"
NEW_IG_NAME="gpu-g6-12x-2b-1"
INSTANCE_COUNT="1"

AWS_REGION="ap-south-2"
INSTANCE_TYPE="ml.g6.12xlarge"
EBS_VOLUME_GB=500
THREADS_PER_CORE=2
CLUSTER_JSON="$(
  aws sagemaker describe-cluster \
    --cluster-name "$HYPERPOD_CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --output json
)"
SOURCE_IG="$(
  jq -ce --arg name "$SOURCE_IG_NAME" \
    '.InstanceGroups[]? | select(.InstanceGroupName == $name)' \
    <<<"$CLUSTER_JSON"
)"
LIFECYCLE_CONFIG="$(jq -c '.LifeCycleConfig' <<<"$SOURCE_IG")"
EXECUTION_ROLE="$(jq -r '.ExecutionRole' <<<"$SOURCE_IG")"
SECURITY_GROUPS="$(
  jq -c --argjson cluster "$CLUSTER_JSON" \
    '.OverrideVpcConfig.SecurityGroupIds // $cluster.VpcConfig.SecurityGroupIds' \
    <<<"$SOURCE_IG"
)"
IMAGE_ID="$(jq -r '.ImageId // empty' <<<"$SOURCE_IG")"
EXISTING_IGS="$(
  jq -c '
    [.InstanceGroups[] |
      {
        InstanceCount: (.TargetCount // .InstanceCount),
        MinInstanceCount: (.MinCount // .MinInstanceCount),
        InstanceGroupName,
        InstanceType,
        LifeCycleConfig,
        ExecutionRole,
        ThreadsPerCore,
        InstanceStorageConfigs,
        OnStartDeepHealthChecks,
        TrainingPlanArn,
        OverrideVpcConfig,
        ScheduledUpdateConfig,
        ImageId,
        CapacityRequirements,
        NetworkInterface
      }
      | with_entries(select(.value != null))
    ]
  ' <<<"$CLUSTER_JSON"
)"
NEW_IG="$(
  jq -n \
    --arg name "$NEW_IG_NAME" \
    --arg type "$INSTANCE_TYPE" \
    --argjson count "$INSTANCE_COUNT" \
    --argjson lifecycle "$LIFECYCLE_CONFIG" \
    --arg role "$EXECUTION_ROLE" \
    --argjson tpc "$THREADS_PER_CORE" \
    --argjson volume "$EBS_VOLUME_GB" \
    --argjson securityGroups "$SECURITY_GROUPS" \
    --arg subnet "$SUBNET_ID" \
    --arg imageId "$IMAGE_ID" \
    '{
      InstanceCount: $count,
      InstanceGroupName: $name,
      InstanceType: $type,
      LifeCycleConfig: $lifecycle,
      ExecutionRole: $role,
      ThreadsPerCore: $tpc,
      InstanceStorageConfigs: [{
        EbsVolumeConfig: {
          VolumeSizeInGB: $volume,
          RootVolume: false
        }
      }],
      OverrideVpcConfig: {
        SecurityGroupIds: $securityGroups,
        Subnets: [$subnet]
      }
    } + if $imageId == "" then {} else {ImageId: $imageId} end'
)"
UPDATE_PAYLOAD="$(
  jq -n \
    --arg clusterName "$HYPERPOD_CLUSTER_NAME" \
    --argjson existing "$EXISTING_IGS" \
    --argjson newGroup "$NEW_IG" \
    '{ClusterName: $clusterName, InstanceGroups: ($existing + [$newGroup])}'
)"
PAYLOAD_FILE="$(mktemp "${TMPDIR:-/tmp}/hyperpod-update-cluster.XXXXXX.json")"
trap 'rm -f "$PAYLOAD_FILE"' EXIT
chmod 600 "$PAYLOAD_FILE"
printf '%s\n' "$UPDATE_PAYLOAD" >"$PAYLOAD_FILE"
aws sagemaker update-cluster \
  --cli-input-json "file://$PAYLOAD_FILE" \
  --region "$AWS_REGION" \
  --output json

