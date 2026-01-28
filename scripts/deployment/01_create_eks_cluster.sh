#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Default values
DEFAULT_EKS_NAME="eks-playground"
DEFAULT_REGION="us-east-1"
DEFAULT_K8S_VERSION="1.31"
DEFAULT_NODE_GROUP_NAME="default-nodegroup"
DEFAULT_NODE_TYPE="t3.medium"
DEFAULT_CREATE_CLUSTER=false
DEFAULT_AWS_PROFILE="staging"

# Function to display usage
usage() {
    echo "Usage: $0 [-e <eks-name>] [-r <region>] [-v <k8s-version>] [-n <node-group-name>] [-t <node-type>] [-p <aws-profile>] [-c]"
    exit 1
}

# Parse command line arguments
while getopts ":e:r:v:n:t:p:c" opt; do
  case $opt in
    e) EKS_NAME="$OPTARG"
    ;;
    r) REGION="$OPTARG"
    ;;
    v) K8S_VERSION="$OPTARG"
    ;;
    n) NODE_GROUP_NAME="$OPTARG"
    ;;
    t) NODE_TYPE="$OPTARG"
    ;;
    p) AWS_PROFILE="$OPTARG"
    ;;
    c) CREATE_CLUSTER=true
    ;;
    \?) echo "Invalid option -$OPTARG" >&2
        usage
    ;;
  esac
done

# Set default values if not provided
EKS_NAME=${EKS_NAME:-$DEFAULT_EKS_NAME}
REGION=${REGION:-$DEFAULT_REGION}
K8S_VERSION=${K8S_VERSION:-$DEFAULT_K8S_VERSION}
NODE_GROUP_NAME=${NODE_GROUP_NAME:-$DEFAULT_NODE_GROUP_NAME}
NODE_TYPE=${NODE_TYPE:-$DEFAULT_NODE_TYPE}
AWS_PROFILE=${AWS_PROFILE:-$DEFAULT_AWS_PROFILE}
CREATE_CLUSTER=${CREATE_CLUSTER:-$DEFAULT_CREATE_CLUSTER}

# Determine the directory of the script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Generate the EKS cluster configuration file in the specified directory
CONFIG_FILE="${SCRIPT_DIR}/../../config/eks/${EKS_NAME}-clusterconfig.yaml"

# Use eksctl to perform a dry run and output the configuration to a file, 此处的 VPC cidr 需要根据自己修改， 避免后期配置peering connecton冲突
eksctl create cluster \
  --name "$EKS_NAME" \
  --region "$REGION" \
  --version "$K8S_VERSION" \
  --nodegroup-name "$NODE_GROUP_NAME" \
  --node-type "$NODE_TYPE" \
  --nodes 1 \
  --nodes-min 1 \
  --nodes-max 3 \
  --managed \
  --full-ecr-access \
  --with-oidc \
  --vpc-cidr "11.0.0.0/16" \
  --dry-run > "$CONFIG_FILE"

echo "Configuration file '$CONFIG_FILE' generated successfully for EKS cluster '$EKS_NAME'."

# Create the EKS cluster if the flag is set
if [ "$CREATE_CLUSTER" = true ]; then
    eksctl create cluster -f "$CONFIG_FILE" --profile "$AWS_PROFILE"
    echo "EKS cluster '$EKS_NAME' created successfully."
fi
