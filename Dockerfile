FROM alpine:3.6

VOLUME [ "/root/.aws" ]

RUN apk add --update python3 alpine-sdk nodejs nodejs-npm zip

COPY . /app

WORKDIR /app

RUN pip3 install -r scripts/requirements.txt

ENTRYPOINT [ "python3", "./scripts/deploy_stack.py" ]