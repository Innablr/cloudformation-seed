FROM alpine:3.6

VOLUME [ "/root/.aws" ]

RUN apk add --update python3 alpine-sdk nodejs nodejs-npm zip

COPY ./scripts/requirements.txt /

RUN pip3 install -r /requirements.txt

COPY . /app

WORKDIR /app

ENTRYPOINT [ "python3", "./scripts/deploy_stack.py" ]