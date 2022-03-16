# Installation

`cloudformation-seed` can be installed and run in a Docker container, or installed as a package from PyPI.

## Docker

### Latest version

```bash
# install
docker pull ghcr.io/innablr/cloudformation-seed:latest
# check version
docker run ghcr.io/innablr/cloudformation-seed:latest cloudformation-seed --version
# run
docker run -e AWS_DEFAULT_REGION=ap-southeast-2 -v /home/me/.aws:/root/.aws ghcr.io/innablr/cloudformation-seed:latest cloudformation-seed -i e0 -e dev -d dev.my-aws-domain.com deploy
```

### A specific version

Replace `0.0.0` with the version that you want to install.

```bash
# install
docker pull ghcr.io/innablr/cloudformation-seed:0.0.0
# check version
docker run ghcr.io/innablr/cloudformation-seed:0.0.0 cloudformation-seed --version
# run
docker run -e AWS_DEFAULT_REGION=ap-southeast-2 -v /home/me/.aws:/root/.aws ghcr.io/innablr/cloudformation-seed:0.0.0 cloudformation-seed -i e0 -e dev -d dev.my-aws-domain.com deploy
```

## PyPI

```bash
# install
pip install cloudformation-seed
# check version
cloudformation-seed --version
```
