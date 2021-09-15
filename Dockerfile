FROM python:3.9-alpine

ARG CFSEED_VERSION

VOLUME [ "/deployment" ]
VOLUME [ "/root/.aws" ]

RUN apk add --update --no-cache make zip unzip
RUN pip install awscli cloudformation-seed==${CFSEED_VERSION}

WORKDIR /deployment
