# CloudFormation Seed

[![Github Actions build and test workflow](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml/badge.svg)](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml)
[![Current cloudformation-seed version on PyPI](https://img.shields.io/pypi/v/cloudformation-seed.svg)](https://pypi.python.org/pypi/cloudformation-seed/)
[![MIT License](https://img.shields.io/github/license/Innablr/cloudformation-seed.svg)](https://github.com/Innablr/cloudformation-seed/blob/main/LICENSE)

## Table of Contents

* [Purpose](#purpose)
* [Installation](#installation)
  * [Docker](#docker)
  * [PyPI](#pypi)
* [Using `cloudformation-seed`](#using-cloudformation-seed)
* [Dependencies and Frameworks](#dependencies-and-frameworks)
* [License](#license)

## Purpose

CloudFormation Seed is a tool for managing multi-stack CloudFormation deployments across different accounts, regions, and environments.  It handles passing parameters between CloudFormation stacks, and uses `StackSet`s to deploy multi-region and multi-account workloads.  Every CloudFormation Seed deployment also creates an S3 bucket, which ican be used to upload and manage CloudFormation templates and other large artefacts such as Lambda code files.

## Installation

`cloudformation-seed` can be installed and run in a Docker container, or installed as a package from PyPI.

### Docker

#### Latest version

```bash
# install
docker pull ghcr.io/innablr/cloudformation-seed:latest
# check version
docker run ghcr.io/innablr/cloudformation-seed:latest cloudformation-seed --version
```

#### A specific version

Replace `0.0.0` with the version that you want to install.

```bash
# install
docker pull ghcr.io/innablr/cloudformation-seed:0.0.0
# check version
docker run ghcr.io/innablr/cloudformation-seed:0.0.0 cloudformation-seed --version
```

### PyPI

```bash
# install
pip install cloudformation-seed
# check version
cloudformation-seed --version
```

## Using `cloudformation-seed`

See [the documentation]() for more details.

You'll need to authenticate to AWS using the CLI before deploying stacks with `cloudformation-seed`.  Amazon's [quick configuration guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html) provides instructions on how to do this if you haven't already.

## Dependencies and frameworks

* [Python](https://www.python.org/)
* [boto3](https://pypi.org/project/boto3/) - AWS SDK for Python
* [colorama](https://pypi.org/project/colorama/) - cross-platform coloured terminal text
* [flake8](https://flake8.pycqa.org/en/latest/) - linting
* [objectpath](http://objectpath.org/) - structured data querying
* [PyYAML](https://pyyaml.org/) - YAML parser for Python

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
