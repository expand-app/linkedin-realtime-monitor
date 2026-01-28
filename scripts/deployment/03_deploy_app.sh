#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Default values
DEFAULT_REGION="us-east-1"
DEFAULT_AWS_ACCOUNT_ID="344318116989"
DEFAULT_AWS_PROFILE="staging"

# Function to display usage
usage() {
    echo "Usage: $0 [-a <app-name>] [-i <image-name>] [-e <env-name>] [-t <target-port>] [-r <region>] [-p <aws-profile>] [-n <aws-account-id>]"
    exit 1
}

# Parse command line arguments
while getopts ":a:i:e:r:p:n:w:u:c:h:" opt; do
  case $opt in
    a) APP_NAME="$OPTARG"
    ;;
    i) IMAGE_NAME="$OPTARG"
    ;;
    e) ENV_NAME="$OPTARG"
    ;;
    r) REGION="$OPTARG"
    ;;
    p) AWS_PROFILE="$OPTARG"
    ;;
    n) AWS_ACCOUNT_ID="$OPTARG"
    ;;
    w) AWS_CLOUDWATCH_ROLE_NAME="$OPTARG"
    ;;
    u) URL="$OPTARG"
    ;;
    c) CERTIFICATE_ID="$OPTARG"
    ;;
    h) REDIS_HOST="$OPTARG"
    ;;
    \?) echo "Invalid option -$OPTARG" >&2
        usage
    ;;
  esac
done

# Set default values if not provided
REGION=${REGION:-$DEFAULT_REGION}
AWS_PROFILE=${AWS_PROFILE:-$DEFAULT_AWS_PROFILE}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-$DEFAULT_AWS_ACCOUNT_ID}

# Check if all required arguments are provided
if [ -z "$APP_NAME" ] || [ -z "$IMAGE_NAME" ] || [ -z "$ENV_NAME" ]; then
    echo "Missing required arguments"
    usage
fi

# Debug: Print the variables
echo "APP_NAME: $APP_NAME"
echo "IMAGE_NAME: $IMAGE_NAME"
echo "ENV_NAME: $ENV_NAME"
echo "REGION: $REGION"
echo "AWS_PROFILE: $AWS_PROFILE"
echo "AWS_ACCOUNT_ID: $AWS_ACCOUNT_ID"
echo "AWS_CLOUDWATCH_ROLE_NAME: $AWS_CLOUDWATCH_ROLE_NAME"
echo "URL: $URL"



sed -e "s|{ { APP_NAME } }|$APP_NAME|g" \
    -e "s|{ { IMAGE_NAME } }|${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${IMAGE_NAME}|g" \
    -e "s|{ { ENV_NAME } }|$ENV_NAME|g" \
    ./config/templates/k8s-deployment-template.yaml > ./config/k8s/$AWS_PROFILE/deployment.yaml

echo 'Generating Kubernetes configuration files...'

sed -e "s|{ { APP_NAME } }|$APP_NAME|g" \
    ./config/templates/k8s-service-template.yaml > ./config/k8s/$AWS_PROFILE/service.yaml

sed -e "s|{ { APP_NAME } }|$APP_NAME|g" \
    ./config/templates/cloudwatch-agent-configmap-template.yaml > ./config/k8s/$AWS_PROFILE/cloudwatch-agent-configmap.yaml


sed -e "s|{ { AWS_ACCOUNT_ID } }|$AWS_ACCOUNT_ID|g" \
    -e "s|{ { AWS_CLOUDWATCH_ROLE_NAME } }|$AWS_CLOUDWATCH_ROLE_NAME|g" \
    ./config/templates/cw-cloudwatch-agent-service-account-template.yaml> ./config/k8s/$AWS_PROFILE/cw-cloudwatch-agent-service-account.yaml

sed -e "s|{ { AWS_ACCOUNT_ID } }|$AWS_ACCOUNT_ID|g" \
    -e "s|{ { APP_NAME } }|$APP_NAME|g" \
    -e "s|{ { URL } }|$URL|g" \
    -e "s|{ { AWS_REGION } }|$REGION|g" \
    -e "s|{ { CERTIFICATE_ID } }|$CERTIFICATE_ID|g" \
    ./config/templates/ingress-template.yaml> ./config/k8s/$AWS_PROFILE/ingress.yaml



# Update kubeconfig for EKS
aws eks update-kubeconfig --region $REGION --profile $AWS_PROFILE --name $APP_NAME
echo "Kubeconfig updated for EKS cluster $APP_NAME."

## Apply Kubernetes configurations
kubectl apply -f ./config/k8s/$AWS_PROFILE/cw-cloudwatch-agent-service-account.yaml
kubectl apply -f ./config/k8s/$AWS_PROFILE/cloudwatch-agent-configmap.yaml

kubectl apply -f ./config/k8s/$AWS_PROFILE/deployment.yaml
kubectl apply -f ./config/k8s/$AWS_PROFILE/service.yaml
kubectl apply -f ./config/k8s/$AWS_PROFILE/ingress.yaml

