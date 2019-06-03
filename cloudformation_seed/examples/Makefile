SHAREDSERVICES_INSTALLATION_NAME ?= x0
SHAREDSERVICES_R53_DOMAIN := my.domain.cld

help:
	@echo ""
	@echo "-- Help Menu"
	@echo ""
	@echo "   1. make project           - build the example project"
	@echo "   2. make project-remove    - delete the example project"
	@echo ""

.DELETE_ON_ERROR:
    echo "============================"
    echo "============================"
    echo "============================"

project:
	INSTALLATION_NAME=$(SHAREDSERVICES_INSTALLATION_NAME) \
	RUNTIME_ENVIRONMENT=dev \
	R53_DOMAIN=$(SHAREDSERVICES_R53_DOMAIN) \
	make -f Makefile.engine deploy

project-remove:
	INSTALLATION_NAME=$(SHAREDSERVICES_INSTALLATION_NAME) \
	RUNTIME_ENVIRONMENT=dev \
	R53_DOMAIN=$(SHAREDSERVICES_R53_DOMAIN) \
	make -f Makefile.engine remove
