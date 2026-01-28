#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Default values
DEFAULT_REGION="us-east-1"
DEFAULT_AWS_ACCOUNT_ID="344318116989"
DEFAULT_EKS_NAME="eks-playground"
DEFAULT_AWS_PROFILE="staging"

# Function to display usage
usage() {
    echo "Usage: $0 [-n <aws-account-id>] [-p <aws-profile>] [-r <region>] [-e <eks-name>] [-o <oidc-provider-url>]"
    exit 1
}

# Parse command line arguments
while getopts ":n:p:r:e:o:w:" opt; do
  case $opt in
    n) AWS_ACCOUNT_ID="$OPTARG"
    ;;
    p) AWS_PROFILE="$OPTARG"
    ;;
    r) REGION="$OPTARG"
    ;;
    e) EKS_NAME="$OPTARG"
    ;;
    o) OIDC_PROVIDER_URL="$OPTARG"
    ;;
    w) ROLE_NAME="$OPTARG"
    ;;
    \?) echo "Invalid option -$OPTARG" >&2
        usage
    ;;
  esac
done

# Set default values if not provided
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-$DEFAULT_AWS_ACCOUNT_ID}
AWS_PROFILE=${AWS_PROFILE:-$DEFAULT_AWS_PROFILE}
REGION=${REGION:-$DEFAULT_REGION}
EKS_NAME=${EKS_NAME:-$DEFAULT_EKS_NAME}

# Check if OIDC_PROVIDER_URL is set
if [ -z "$OIDC_PROVIDER_URL" ]; then
    echo "OIDC_PROVIDER_URL is required."
    usage
fi

# Debug: Print the variables
echo "AWS_ACCOUNT_ID: $AWS_ACCOUNT_ID"
echo "AWS_PROFILE: $AWS_PROFILE"
echo "REGION: $REGION"
echo "EKS_NAME: $EKS_NAME"
echo "OIDC_PROVIDER_URL: $OIDC_PROVIDER_URL"
echo "ROLE_NAME: $ROLE_NAME"

# Use AWS managed policy ARN
POLICY_ARN="arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"

# Check if the role already exists
if aws iam get-role --role-name $ROLE_NAME --profile $AWS_PROFILE > /dev/null 2>&1; then
    echo "Role $ROLE_NAME already exists."
else
    # Create role using inline JSON for trust policy and suppress output
    aws iam create-role \
      --role-name $ROLE_NAME \
      --assume-role-policy-document "{
          \"Version\": \"2012-10-17\",
          \"Statement\": [
            {
              \"Effect\": \"Allow\",
              \"Principal\": {
                \"Federated\": \"arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER_URL}\"
              },
              \"Action\": \"sts:AssumeRoleWithWebIdentity\",
              \"Condition\": {
                \"StringEquals\": {
                  \"${OIDC_PROVIDER_URL}:sub\": \"system:serviceaccount:default:cloudwatch-agent-service-account\"
                }
              }
            }
          ]
        }" \
      --profile $AWS_PROFILE > /dev/null
    echo "Role $ROLE_NAME created."
fi

# Attach AWS managed policy to the role
aws iam attach-role-policy \
  --role-name $ROLE_NAME \
  --policy-arn $POLICY_ARN \
  --profile $AWS_PROFILE
echo "AWS managed policy attached to role $ROLE_NAME."

