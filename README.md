# CloudFormation Seed

[![Github Actions build and test workflow](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml/badge.svg)](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml)
[![Current cloudformation-seed version on PyPI](https://img.shields.io/pypi/v/cloudformation-seed.svg)](https://pypi.python.org/pypi/cloudformation-seed/)
[![MIT License](https://img.shields.io/github/license/Innablr/cloudformation-seed.svg)](https://github.com/Innablr/cloudformation-seed/blob/main/LICENSE)

## Table of Contents

* [Purpose](#purpose)
* [Requirements](#requirements)
* [Installation](#installation)
  * [Docker](#docker)
  * [PyPI](#pypi)
* [Using `cloudformation-seed`](#using-cloudformation-seed)
* [Dependencies and Frameworks](#dependencies-and-frameworks)
* [License](#license)

## Purpose

This is a script that will help you deploy your Cloudformation project without hassle:

* Handle Cloudformation deployments of any scale
* Allow to do multiple deployments of the same code with a different installation name
* Automate Lambda code handling
* Get rid of hard dependencies of Cloudformation Exports, instead pass around Output values between stacks
* Package the whole deployment in a Docker image and version it

It will:

* Automatically create an S3 bucket according to the project name
* Upload the Cloudformation templates into the bucket
* Package and checksum your Lambda code and upload it into the bucket
* Upload arbitrary artifacts into the bucket so that they are available to your deployment
* Create and manage Cloudformation stacks
* Create, roll out and manage Stacksets

## Requirements

You need a Mac, Linux or Windows machine/VM to run the Seed. On Windows it runs natively, as well as in WSL/WSL2.

## Installation

### Docker



```
$ docker pull ghcr.io/innablr/cloudformation-seed:latest
$ docker run ghcr.io/innablr/cloudformation-seed:latest cloudformation-seed --version
```

### PyPI

```
$ pip install cloudformation-seed
$ cloudformation-seed --version
```

## Using `cloudformation-seed`

### AWS CLI Authentication

Authenticate to AWS using your method of choice, make sure that you have set the AWS Region you need for deployment.

 

## Dependencies and frameworks

* [Python](https://www.python.org/)
* [boto3](https://pypi.org/project/boto3/) - AWS SDK for Python
* [colorama](https://pypi.org/project/colorama/) - cross-platform coloured terminal text
* [flake8](https://flake8.pycqa.org/en/latest/) - linting
* [objectpath](http://objectpath.org/) - structured data querying
* [PyYAML](https://pyyaml.org/) - YAML parser for Python

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
