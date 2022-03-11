# CloudFormation Seed

[![Github Actions build and test workflow](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml/badge.svg)](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml)
[![Current cloudformation-seed version on PyPI](https://img.shields.io/pypi/v/cloudformation-seed.svg)](https://pypi.python.org/pypi/cloudformation-seed/)
<!---
[![Current Python version](https://img.shields.io/github/license/Innablr/cloudformation-seed.svg)](https://github.com/Innablr/cloudformation-seed/blob/main/LICENSE)
--->
[![MIT License](https://img.shields.io/github/license/Innablr/cloudformation-seed.svg)](https://github.com/Innablr/cloudformation-seed/blob/main/LICENSE)

## Table of Contents

* [Purpose](#purpose)
* [Requirements](#requirements)
* [Installation Instructions](#installation-instructions)
  * [Docker](#docker)
  * [PyPI](#pypi)
* [Documentation](#documentation)
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

## Installation Instructions

### Docker

(version number for stability)

```
$ docker pull ghcr.io/innablr/cloudformation-seed:latest
$ docker run ghcr.io/innablr/cloudformation-seed:latest cloudformation-seed --version
```

### PyPI

```
$ pip install cloudformation-seed
$ cloudformation-seed --version
```

## Quick Start Guide

### AWS CLI Authentication

Authenticate to AWS using your method of choice, make sure that you have set the AWS Region you need for deployment.

### Project Setup

1. Create a new directory for your project
2. Copy everything from the `examples` directory to the root of the project

**Dawn Note:** there is going to be a balance between explaining the folder structure and not overloading the user with information.

### Modifying Parameters

3. Edit `parameters/dev.yaml` to your needs

**Dawn Note:** this needs a lot more information, some of which can potentially be pulled out of the deep dive.

### Deploying Templates

Run `cloudformation-seed -c my-project -i x0 -e dev -d my.domain.cld deploy`

**Dawn Note:** what do the flags do?  That ought to be explained somewhere.

## Customisation

## Release Management

cloudformation-seed also can read a release manifest file if you specify it in the `-m` commandline argument. Release manifest contains artifact names, their versions and other information about the software that is being deployed by the Seed. You can then inform your Cloudformation stacks about the versions and images you are deploying using the `!ArtifactVersion`, `!ArtifactRepo` and `!ArtifactImage` tags in the runtime environment configuration.

More documentation about release management is coming soon.

## Dependencies and frameworks

* [Python dependencies - placeholder]() 

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
