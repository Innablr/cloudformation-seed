-include Makefile.particulars

DEBUG ?= 0
AWS_DEFAULT_REGION ?= ap-southeast-2
AWS_ORG ?=
COMPONENT_NAME ?= generic-ops
IMAGE_NAME ?= $(COMPONENT_NAME):latest

ENVS ?= --env AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION)
AWS_ORG_FLAG :=
DEBUG_FLAG :=

ifneq ($(AWS_PROFILE),)
ENVS += --env AWS_PROFILE=$(AWS_PROFILE)
endif

ifneq ($(AWS_ORG),)
AWS_ORG_FLAG := -o $(AWS_ORG)
endif

ifeq ($(DEBUG),1)
DEBUG_FLAG := -v
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
		$(IMAGE_NAME) $(DEBUG_FLAG) -c $(COMPONENT_NAME) -i $(INSTALLATION_NAME) -e $(RUNTIME_ENVIRONMENT) -d $(R53_DOMAIN) $(AWS_ORG_FLAG) deploy

remove: build
	if [ -z "${INSTALLATION_NAME}" -o -z "${RUNTIME_ENVIRONMENT}" -o -z "${R53_DOMAIN}" ]; then \
		echo "You must set INSTALLATION_NAME, RUNTIME_ENVIRONMENT and R53_DOMAIN"; \
		exit 4; \
	fi
	docker run \
		-v ~/.aws:/root/.aws \
		$(ENVS) -t --rm \
		$(IMAGE_NAME) $(DEBUG_FLAG) -c $(COMPONENT_NAME) -i $(INSTALLATION_NAME) -e $(RUNTIME_ENVIRONMENT) -d $(R53_DOMAIN) $(AWS_ORG_FLAG) teardown

.PHONY: build deploy remove

-include Makefile.targets
