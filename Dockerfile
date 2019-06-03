FROM alpine:3.8 AS base
VOLUME /root/.aws
VOLUME /app
WORKDIR /app
RUN apk add --update python3 alpine-sdk nodejs nodejs-npm zip

FROM base AS dependencies
COPY . /app
RUN python3 setup.py install

FROM dependencies AS test
RUN flake8
RUN python3 -m unittest -v

FROM base AS release
COPY --from=dependencies . .

ENTRYPOINT [ "cloudformation-seed" ]