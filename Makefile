env=staging
capitalized_env := $(shell printf "%s" "${env}" | cut -c1 | tr a-z A-Z)$(shell printf "%s" "${env}" | cut -c2-)
target_service=lkrm
upper_cased_target_service := $(shell echo "$(target_service)" | tr '[:lower:]' '[:upper:]')
version_file_name=version_check.txt
uuid=$$(uuidgen)
timestamp=$$(date)
cluster_name=${target_service}-${env}
ifeq ($(env), prod)
    oidc_url=oidc.eks.us-east-1.amazonaws.com/id/C559B395E68B4D1E8D31CFBE1972DA4B
else
    oidc_url=oidc.eks.us-east-1.amazonaws.com/id/78525859448DB3698EA2DC88DACE20F6

endif


# 使用 shell 函数从文件中读取版本
image_version := $(shell cat current_image_version.txt)
ifeq ($(env), prod)
    instance_type := c6i.2xlarge
    cloudwatch_role_name := LKRMEKSCloudWatchAgentRole
    aws_account := 625719641746
    url := 	lkrm.api.tuilink.io
    CERTIFICATE_ID := ab0dcc4f-3197-4163-b2c0-cdd1e3360de4
    vpc_id := vpc-0113b098dcc8a9adc
    redis_host := lkrm-prod-redis-to-k8s.yh1jo9.ng.0001.use1.cache.amazonaws.com
else
    instance_type := c6i.2xlarge
    cloudwatch_role_name := LKRMStaingEKSCloudWatchAgentRole
    aws_account := 344318116989
    url := 	lkrm.api.staging.tuilink.io
    CERTIFICATE_ID := 6473ed4d-c43c-4ba3-a587-9cbd3e87ea55
    vpc_id := vpc-0663fb04310e2646f
    redis_host := lkrmm-staging.7a35g2.ng.0001.use1.cache.amazonaws.com
endif

start:
	Env=${env} LocalDev=True python manage.py runserver

makemigrations:
	Env=${env} python manage.py makemigrations

migrate:
	Env=${env} python manage.py migrate

collectstatic:
	Env=${env} python manage.py collectstatic


build-cw-agent-config:
	# Replace `${capitalized_env}` with the capitalized environment name, e.g. replacing `LKRMBackend-${capitalized_env}-DjangoEnvironment` with `LKRMBackend-Staging-DjangoEnvironment`
	# when `capitalized_env` is `Staging`
	sed -e "s|\$${capitalized_env}|${capitalized_env}|g" \
		-e "s|\$${upper_cased_target_service}|${upper_cased_target_service}|g" \
		".platform/amazon-cloudwatch-agent-base.json" > ".platform/amazon-cloudwatch-agent.json"

build:
	make clean
	make collectstatic
	rsync -av --exclude=geckodriver.log --exclude=*.ipynb --exclude=.elasticbeanstalk/ --exclude=.git --exclude=*/__pycache__/  --exclude=.vscode --exclude=dist.zip --exclude=*.DS_Store --exclude=.gitignore --exclude=env --exclude=.idea --exclude=.venv --exclude=venv --exclude=env ./ ./dist

clean:
	rm -rf ./dist.zip ./dist ./files

deploy:
	make build
	cd ../infra-aws; \
	yarn deploy-${target_service}b:${env} --profile ${env}

remove-codecommit:
	git remote remove codecommit-origin

init-eb:
	make remove-codecommit || true
	yes n | eb init --profile ${env}
	eb use ${upper_cased_target_service}Backend-${capitalized_env}-DjangoEnvironment --profile ${env}
	
requirements:
	pip list > requirements.txt --format freeze

enable-logging:
	aws eks update-cluster-config --region us-east-1 --profile ${env}  \
	  --name ${cluster_name}\
	  --logging '{"clusterLogging":[{"types":["api","audit","authenticator","controllerManager","scheduler"],"enabled":true}]}'

get-OIDC-URL:
	aws eks --region us-east-1 --profile ${env} describe-cluster --name ${cluster_name} \
  		--query "cluster.identity.oidc.issuer" --output text

associate-OIDC-Provider:
	eksctl utils associate-iam-oidc-provider \
	  --region us-east-1 \
	  --profile ${env} \
	  --cluster ${cluster_name} \
	  --approve

iam-serviceaccount:
	eksctl create iamserviceaccount \
	  --cluster ${cluster_name} \
	  --namespace kube-system \
	  --name aws-lkrm-load-balancer-controller \
	  --attach-policy-arn arn:aws:iam::${aws_account}:policy/AWSLoadBalancerControllerIAMPolicy \
	  --approve \
	  --override-existing-serviceaccounts \
	  --region us-east-1 \
	  --profile ${env}

create-iam-policy:
	curl -o iam-policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json
	aws --profile ${env} iam create-policy \
	  --policy-name AWSLoadBalancerControllerIAMPolicy \
	  --policy-document file://iam-policy.json


create-helm-repo:
	helm repo add eks https://aws.github.io/eks-charts
	helm repo update


create-alb:
	# Step 1: Enable EKS Control Plane Logging
	make enable-logging
	# Step 2: Create IAM OIDC Provider
	make get-OIDC-URL
	# Step 3: Associate IAM OIDC Provider with EKS Cluster
	make associate-OIDC-Provider
	# Step 4: Create IAM Policy
	make create-iam-policy
	# Step 5: Create IAM Service Account
	make iam-serviceaccount
	# Step 6: Create Helm Repository
	make create-helm-repo
	# Step 7: Install AWS Load Balancer Controller
	helm install lkrm-staging-alb eks/aws-load-balancer-controller \
	  -n kube-system \
	  --set clusterName=${cluster_name} \
	  --set serviceAccount.create=false \
	  --set serviceAccount.name=aws-lkrm-load-balancer-controller \
	  --set region=us-east-1 \
	  --set vpcId=${vpc_id} \
	  --set image.tag="v2.7.1"  # 根据实际版本更新

create-ingress-class:
	kubectl apply -f ./config/eks/ingress-class.yaml

prepare-cloud-watch-agent-auth:
	./scripts/deployment/04_prepare_cw_agent_auth.sh -e ${target_service}-${env} -o ${oidc_url} -r us-east-1 -n ${aws_account} -p ${env} -w ${cloudwatch_role_name}

create-cluster:
	./scripts/deployment/01_create_eks_cluster.sh -e ${target_service}-${env} -r us-east-1 -v 1.31 -n default-nodegroup-1 -t ${instance_type} -p ${env} -c

delete-cluster:
	eksctl delete cluster ${target_service}-${env}

build-image:
	aws ecr get-login-password --region us-east-1 --profile ${env} | docker login --username AWS --password-stdin ${aws_account}.dkr.ecr.us-east-1.amazonaws.com
	make generate
	./scripts/deployment/02_prepare_app_assets.sh -a ${target_service}-${env} -r us-east-1 -n ${aws_account} -p ${env}

# 这条命令用于在build-image失败的时候使用(一般是push镜像的时候出了网络错误)， 可以将镜像再推送一次， 而不用再重新build
push-image:
	docker push  ${aws_account}.dkr.ecr.us-east-1.amazonaws.com/${image_version}

deploy-k8s:
	@echo ${image_version}
	./scripts/deployment/03_deploy_app.sh -a ${target_service}-${env} -i ${image_version} -e ${env} -r us-east-1 -n ${aws_account} -p ${env} -w ${cloudwatch_role_name} -u ${url} -c ${CERTIFICATE_ID} -h ${redis_host}

generate:
	# 先清空文件
	@echo '' > $(version_file_name)
	@echo "生成文件: $(version_file_name)"
	@echo "Publish start at ${timestamp}" >> $(version_file_name)
	@echo "<br>" >> $(version_file_name)
	@echo  "Version uuid: ${uuid}" >> $(version_file_name)
	@echo "UUID 和生成时间已写入 $(version_file_name)"

kgc:
	kubectl config get-contexts

ssh-p:
	@if [ -z "$(n)" ]; then n=default; fi; \
	kubectl exec -it $(p) -n $$n -- /bin/bash

ssh-c:
	@if [ -z "$(n)" ]; then n=default; fi; \
	kubectl config use-context $(c);

create-ac-policy:
	aws --profile ${env} iam create-policy \
	--policy-name AmazonEKSClusterAutoscalerPolicy \
	--policy-document file://./config/AmazonEKSClusterAutoscalerPolicy.json

get-vpc-id:
	aws eks --region us-east-1 --profile ${env} describe-cluster \
	--name ${cluster_name} --query "cluster.resourcesVpcConfig.vpcId" --output text

create-ac-serviceaccount:
	eksctl create iamserviceaccount \
	  --cluster ${cluster_name} \
	  --namespace kube-system \
	  --name cluster-autoscaler \
	  --attach-policy-arn arn:aws:iam::${aws_account}:policy/AmazonEKSClusterAutoscalerPolicy \
	  --approve \
	  --override-existing-serviceaccounts \
	  --region us-east-1 \
	  --profile ${env}