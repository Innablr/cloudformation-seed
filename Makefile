-include Makefile.particulars

AWS_DEFAULT_REGION ?= ap-southeast-2
COMPONENT_NAME ?= generic-ops
IMAGE_NAME ?= $(COMPONENT_NAME):latest

ifeq ($(AWS_PROFILE),)
ENVS ?= --env AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION)
else
ENVS ?= --env AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION) --env AWS_PROFILE=$(AWS_PROFILE)
endif

build:
	docker build \
        --tag $(IMAGE_NAME) \
		--file scripts/Dockerfile .

deploy: build
	if [ -z "${INSTALLATION_NAME}" -o -z "${RUNTIME_ENVIRONMENT}" -o -z "${R53_DOMAIN}" ]; then \
		echo "You must set INSTALLATION_NAME, RUNTIME_ENVIRONMENT and R53_DOMAIN"; \
		exit 4; \
	fi
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -c $(COMPONENT_NAME) -i $(INSTALLATION_NAME) -e $(RUNTIME_ENVIRONMENT) -d $(R53_DOMAIN) --cap-iam --cap-named-iam deploy

remove: build
	if [ -z "${INSTALLATION_NAME}" -o -z "${RUNTIME_ENVIRONMENT}" -o -z "${R53_DOMAIN}" ]; then \
		echo "You must set INSTALLATION_NAME, RUNTIME_ENVIRONMENT and R53_DOMAIN"; \
		exit 4; \
	fi
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) -c $(COMPONENT_NAME) -i $(INSTALLATION_NAME) -e $(RUNTIME_ENVIRONMENT) -d $(R53_DOMAIN) --cap-iam --cap-named-iam teardown

.PHONY: build deploy remove

-include Makefile.targets
