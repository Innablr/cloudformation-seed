AWS_DEFAULT_REGION ?= ap-southeast-2
COMPONENT_NAME ?= centralservices-ops
IMAGE_NAME ?= $(COMPONENT_NAME):latest

ifeq ($(AWS_PROFILE),)
ENVS ?= --env AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION)
else
ENVS ?= --env AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION) --env AWS_PROFILE=$(AWS_PROFILE)
endif

build:
	docker build \
        --tag $(IMAGE_NAME) \
		--file Dockerfile .

deploy: build
	if [ -z "${INSTALLATION_NAME}" -o -z "${RUNTIME_ENVIRONMENT}" -o -z "${R53_DOMAIN}" ]; then \
		echo "You must set INSTALLATION_NAME, RUNTIME_ENVIRONMENT and R53_DOMAIN"; \
		exit 4; \
	fi
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -i $(INSTALLATION_NAME) -e $(RUNTIME_ENVIRONMENT) -d $(R53_DOMAIN) --cap-iam --cap-named-iam deploy

remove: build
	if [ -z "${INSTALLATION_NAME}" -o -z "${RUNTIME_ENVIRONMENT}" -o -z "${R53_DOMAIN}" ]; then \
		echo "You must set INSTALLATION_NAME, RUNTIME_ENVIRONMENT and R53_DOMAIN"; \
		exit 4; \
	fi
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -i $(INSTALLATION_NAME) -e $(RUNTIME_ENVIRONMENT) -d $(R53_DOMAIN) --cap-iam --cap-named-iam teardown

root: build
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -i rc0 -e root -d prod.mebank-root.cld --cap-iam --cap-named-iam deploy

primecs: build
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -i rc0 -e primecs -d prod.centralservices.cld --cap-iam --cap-named-iam deploy

primeaccount: build
	if [ -z "${R53_DOMAIN}" ]; then \
		echo "You must set R53_DOMAIN"; \
		exit 4; \
	fi
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -i rc0 -e primeaccount -d $(R53_DOMAIN) --cap-iam --cap-named-iam deploy

world: build
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -i r0 -e prod -d prod.centralservices.cld --cap-iam --cap-named-iam deploy


.PHONY: build deploy remove root primecs primeaccount world
