FROM alpine:3.8

VOLUME /root/.aws
VOLUME /app

RUN apk add --update python3 alpine-sdk nodejs nodejs-npm zip

RUN pip3 install --upgrade pip && pip3 install cloudformation-seed==0.9.2

WORKDIR /app

ENTRYPOINT [ "cloudformation-seed" ]