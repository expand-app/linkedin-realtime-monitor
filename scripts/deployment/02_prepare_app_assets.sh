#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Default values
DEFAULT_APP_NAME="eks-playground"
DEFAULT_REGION="us-east-1"
DEFAULT_AWS_ACCOUNT_ID="344318116989"
DEFAULT_AWS_PROFILE="staging"

# Function to display usage
usage() {
    echo "Usage: $0 [-a <app-name>] [-p <aws-profile>] [-r <region>] [-n <aws-account-id>]"
    exit 1
}

# Parse command line arguments
while getopts ":a:p:r:n:" opt; do
  case $opt in
    a) APP_NAME="$OPTARG"
    ;;
    p) AWS_PROFILE="$OPTARG"
    ;;
    r) REGION="$OPTARG"
    ;;
    n) AWS_ACCOUNT_ID="$OPTARG"
    ;;
    \?) echo "Invalid option -$OPTARG" >&2
        usage
    ;;
  esac
done

# Set default values if not provided
APP_NAME=${APP_NAME:-$DEFAULT_APP_NAME}
REGION=${REGION:-$DEFAULT_REGION}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-$DEFAULT_AWS_ACCOUNT_ID}
AWS_PROFILE=${AWS_PROFILE:-$DEFAULT_AWS_PROFILE}

# Append a custom version number to the image name
VERSION=$(date +%Y.%m%d.%H%M%S)
FULL_IMAGE_NAME="${APP_NAME}:${VERSION}"

# Log the full image name
echo "Building Docker image with name: $FULL_IMAGE_NAME"
echo "AWS_PROFILE: ${AWS_PROFILE}"

# Build the Docker image
#docker buildx build -f Dockerfile.staging --platform linux/amd64 -t $FULL_IMAGE_NAME .
docker build --file Dockerfile.${AWS_PROFILE} --platform linux/amd64 -t $FULL_IMAGE_NAME .
echo "Docker image $FULL_IMAGE_NAME built successfully."

# Check if the ECR repository exists, create if it doesn't
if ! aws ecr describe-repositories --repository-names $APP_NAME --profile $AWS_PROFILE --region $REGION > /dev/null 2>&1; then
    aws ecr create-repository --repository-name $APP_NAME --profile $AWS_PROFILE --region $REGION > /dev/null
    echo "ECR repository $APP_NAME created."
else
    echo "ECR repository $APP_NAME already exists."
fi

# Get the login password and login to ECR
aws ecr get-login-password --region $REGION --profile $AWS_PROFILE | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

#aws ecr get-login-password --region us-east-1 --profile staging | docker login --username AWS --password-stdin 344318116989.dkr.ecr.us-east-1.amazonaws.com

echo "Logged into ECR successfully."

# Tag and push the Docker image
docker tag $FULL_IMAGE_NAME $AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$APP_NAME:$VERSION
echo "Docker image tagged as $AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$APP_NAME:$VERSION."

# 将需要发布的镜像的版本写入本地文件, 如果只是推送镜像失败了， 运行 make push-image 手动推送一次
echo $APP_NAME:$VERSION > current_image_version.txt

docker push $AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$APP_NAME:$VERSION
echo "Docker image pushed to ECR: $AWS_ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$APP_NAME:$VERSION."

