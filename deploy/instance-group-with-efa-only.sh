#!/usr/bin/env bash
#
# Requires: aws cli v2, jq
set -euo pipefail

# ---- cluster name / region: 默认从 infrastructure/cdk.json 读 (env 可覆盖) ----
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CDK_JSON="$ROOT/infrastructure/cdk.json"
ctx() { python3 -c "import json,sys; print(json.load(open('$CDK_JSON'))['context'].get('$1',''))" 2>/dev/null; }
# Use the ClusterName from `aws sagemaker describe-cluster` (the SageMaker HyperPod cluster name).
HYPERPOD_CLUSTER_NAME="${HYPERPOD_CLUSTER_NAME:-$(ctx hyperpodClusterName)}"
REGION="${REGION:-$(ctx region)}"        # AWS region
: "${HYPERPOD_CLUSTER_NAME:?需要 cdk.json hyperpodClusterName 或 export HYPERPOD_CLUSTER_NAME}"
: "${REGION:?需要 cdk.json region 或 export REGION}"
NEW_IG_NAME="worker-efa-only"            # Name of the new instance group (must not clash with an existing one)
INSTANCE_TYPE="ml.g6e.48xlarge"           # Instance type for the new group (must be a multi-EFA-card type)
INSTANCE_COUNT=2                         # Number of instances in the new group
TRAINING_PLAN_ARN=""                     # Training Plan ARN (leave "" for none -> On-Demand)
# ★REQUIRED★ Subnet ID for the new group. The subnet uniquely determines the AZ (the script looks it up and prints it).
SUBNET_ID="subnet-0123456789abcdef0"
# ★REQUIRED★ Name of the existing "source instance group". The new group inherits these common settings from it:
#   - LifeCycleConfig            : lifecycle script S3 location (SourceS3Uri) and entrypoint (OnCreate)
#   - ExecutionRole              : instance group execution role
#   - OverrideVpcConfig.SecurityGroupIds : security groups
SOURCE_IG_NAME="cpu-spt"
EBS_VOLUME_GB="500"
DEEP_HEALTH_CHECKS=""         # InstanceStress / InstanceConnectivity / InstanceStress,InstanceConnectivity
# Instance types eligible for efa-only (multi-EFA-card types), from ui-panel/config/efa-only-instance-types.json
EFA_ONLY_ELIGIBLE=(
  ml.p4d.24xlarge ml.p4de.24xlarge
  ml.p5.48xlarge ml.p5e.48xlarge ml.p5en.48xlarge
  ml.p6-b200.48xlarge ml.p6-b300.48xlarge
  ml.g6e.24xlarge ml.g6e.48xlarge
  ml.g7e.24xlarge ml.g7e.48xlarge
)
# ---- Pre-checks ---------------------------------------------------------------
command -v aws >/dev/null || { echo "ERROR: aws cli not found" >&2; exit 1; }
command -v jq  >/dev/null || { echo "ERROR: jq not found" >&2; exit 1; }
[[ -n "$SUBNET_ID" && "$SUBNET_ID" != "subnet-xxxxxxxx" ]] || { echo "ERROR: SUBNET_ID is required; set the subnet ID for the new group." >&2; exit 1; }
[[ -n "$SOURCE_IG_NAME" && "$SOURCE_IG_NAME" != "existing-ig-name" ]] || { echo "ERROR: SOURCE_IG_NAME is required; set the source instance group to inherit from." >&2; exit 1; }
# ---- 1. Fetch cluster config --------------------------------------------------
echo "describe-cluster: $HYPERPOD_CLUSTER_NAME ($REGION)"
CLUSTER_JSON="$(aws sagemaker describe-cluster --cluster-name "$HYPERPOD_CLUSTER_NAME" --region "$REGION" --output json)" \
  || { echo "ERROR: describe-cluster failed; check cluster name / region / credentials" >&2; exit 1; }
# The new group name must not collide with an existing group
if echo "$CLUSTER_JSON" | jq -e --arg n "$NEW_IG_NAME" '.InstanceGroups[]|select(.InstanceGroupName==$n)' >/dev/null 2>&1; then
  echo "ERROR: Instance group '$NEW_IG_NAME' already exists; choose a different name." >&2; exit 1
fi
# ---- 2. Read the source group and inherit fields ------------------------------
SRC="$(echo "$CLUSTER_JSON" | jq -e --arg n "$SOURCE_IG_NAME" '.InstanceGroups[]|select(.InstanceGroupName==$n)')" \
  || { echo "ERROR: Source group '$SOURCE_IG_NAME' not found. Existing: $(echo "$CLUSTER_JSON" | jq -r '[.InstanceGroups[].InstanceGroupName]|join(", ")')" >&2; exit 1; }
SRC_LIFECYCLE="$(echo "$SRC" | jq -c '.LifeCycleConfig // empty')"
SRC_ROLE="$(echo "$SRC" | jq -r '.ExecutionRole // empty')"
SRC_SGS="$(echo "$SRC" | jq -c '.OverrideVpcConfig.SecurityGroupIds // empty')"
# Inherit strictly from the source group; error out if missing (no fallback to cluster-level VpcConfig)
[[ -n "$SRC_LIFECYCLE" ]] || { echo "ERROR: Source group has no LifeCycleConfig; cannot inherit." >&2; exit 1; }
[[ -n "$SRC_ROLE" ]]      || { echo "ERROR: Source group has no ExecutionRole; cannot inherit." >&2; exit 1; }
[[ -n "$SRC_SGS" ]]       || { echo "ERROR: Source group '$SOURCE_IG_NAME' has no OverrideVpcConfig.SecurityGroupIds; cannot inherit security groups." >&2; exit 1; }
# ---- 3. Subnet: use the required SUBNET_ID, look up its AZ ---------------------
S_AZ="$(aws ec2 describe-subnets --subnet-ids "$SUBNET_ID" --region "$REGION" --query 'Subnets[0].AvailabilityZone' --output text)" \
  || { echo "ERROR: failed to validate SUBNET_ID (subnet missing or no permission)" >&2; exit 1; }
echo "Using subnet: $SUBNET_ID (AZ $S_AZ)"
# ---- 4. ThreadsPerCore: fixed at 2 (typical for GPU training types) -----------
TPC=2
# ---- 5. EBS storage (driven by EBS_VOLUME_GB, not inherited) ------------------
STORAGE_JSON="$(jq -n --argjson gb "$EBS_VOLUME_GB" '[{EbsVolumeConfig:{VolumeSizeInGB:$gb,RootVolume:false}}]')"
# ---- 5b. Deep health checks (driven by DEEP_HEALTH_CHECKS, not inherited) ------
if [[ -n "$DEEP_HEALTH_CHECKS" ]]; then
  HEALTH_JSON="$(echo "$DEEP_HEALTH_CHECKS" | jq -R 'split(",") | map(gsub("^\\s+|\\s+$";"")) | map(select(length>0))')"
else
  HEALTH_JSON="null"
fi
# ---- 6. Instance-type pre-check (warn only) -----------------------------------
ELIGIBLE=0
for t in "${EFA_ONLY_ELIGIBLE[@]}"; do [[ "$t" == "$INSTANCE_TYPE" ]] && ELIGIBLE=1 && break; done
[[ "$ELIGIBLE" -eq 1 ]] || echo "WARN: instance type '$INSTANCE_TYPE' is not in the known efa-only list (multi-EFA-card types); AWS may reject it." >&2
# ---- 7. Assemble the new group spec -------------------------------------------
NEW_IG="$(jq -n \
  --arg name "$NEW_IG_NAME" \
  --arg type "$INSTANCE_TYPE" \
  --argjson count "$INSTANCE_COUNT" \
  --argjson lifecycle "$SRC_LIFECYCLE" \
  --arg role "$SRC_ROLE" \
  --argjson tpc "$TPC" \
  --argjson storage "$STORAGE_JSON" \
  --argjson sgs "$SRC_SGS" \
  --arg subnet "$SUBNET_ID" \
  --arg tparn "$TRAINING_PLAN_ARN" \
  --argjson health "$HEALTH_JSON" \
  '{
     InstanceCount: $count,
     InstanceGroupName: $name,
     InstanceType: $type,
     LifeCycleConfig: $lifecycle,
     ExecutionRole: $role,
     ThreadsPerCore: $tpc,
     InstanceStorageConfigs: $storage,
     OverrideVpcConfig: { SecurityGroupIds: $sgs, Subnets: [$subnet] },
     NetworkInterface: { InterfaceType: "efa-only" }
   }
   + (if $tparn  != "" then {TrainingPlanArn: $tparn} else {} end)
   + (if $health != null then {OnStartDeepHealthChecks: $health} else {} end)
  ')"
IGS="$(jq -n --argjson ig "$NEW_IG" '[$ig]')"
# ---- 8. Show the spec and the command -----------------------------------------
echo
echo "New efa-only instance group spec:"
echo "$NEW_IG" | jq .
echo
echo "Inherited from source group: $SOURCE_IG_NAME | subnet: $SUBNET_ID (AZ $S_AZ) | ThreadsPerCore: $TPC"
echo
echo "Full command (review before running):"
echo "  aws sagemaker update-cluster --cluster-name \"$HYPERPOD_CLUSTER_NAME\" --instance-groups '$IGS' --region \"$REGION\""
echo
# To actually create the instance group, uncomment the line below and re-run:
# aws sagemaker update-cluster --cluster-name "$HYPERPOD_CLUSTER_NAME" --instance-groups "$IGS" --region "$REGION"