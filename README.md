# CloudFormation Seed

[![Github Actions build and test workflow](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml/badge.svg)](https://github.com/Innablr/cloudformation-seed/actions/workflows/build-and-test.yaml)
[![Current cloudformation-seed version on PyPI](https://img.shields.io/pypi/v/cloudformation-seed.svg)](https://pypi.python.org/pypi/cloudformation-seed/)
[![Python 3.7 - placeholder]()]()
[![MIT License - placeholder]()]()

## Table of Contents

* [Purpose](#purpose)
  * [Basic Features?]
  * [Complicated Features?]
* [Requirements](#requirements)
* [Installation Instructions](#installation-instructions)
  * [PyPI](#pypi)
  * [Docker](#docker)
* [Quick Start Guide](#quick-start-guide)
  * [AWS CLI Authentication](#aws-cli-authentication)
  * [Project Setup](#project-setup)
  * [Modifying Parameters](#modifying-parameters)
  * [Adding Templates](#adding-templates)
  * [Deploying Templates](#deploying-templates)
  * [Modifying Dockerfiles](#modifying-dockerfiles)
  * [Modifying Makefiles](#modifying-makefiles)
* [Release Management](#release-management)
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

### PyPI

```
$ pip install cloudformation-seed
$ cloudformation-seed --version
```

### Docker

(version number for stability)

```
$ docker pull ghcr.io/innablr/cloudformation-seed:latest
$ docker run ghcr.io/innablr/cloudformation-seed:latest cloudformation-seed --version
```

## Quick Start Guide

**Dawn Note:** I'm tempted to have this as just 'deploy the test Lambda to one or more accounts', and move the configuration instructions into other files to avoid the main README becoming too dense.

### AWS CLI Authentication

Authenticate to AWS using your method of choice, make sure that you have set the AWS Region you need for deployment.

### Project Setup

1. Create a new directory for your project
2. Copy everything from the `examples` directory to the root of the project

**Dawn Note:** there is going to be a balance between explaining the folder structure and not overloading the user with information.

### Modifying Parameters

3. Edit `parameters/dev.yaml` to your needs

**Dawn Note:** this needs a lot more information, some of which can potentially be pulled out of the deep dive.

### Adding Templates

4. Add more templates with `.cf.yaml` extensions under the `cloudformation` directory and include them in `parameters/dev.yaml`

**Dawn Note:** do the templates require any sort of special configuration to work with `cf-seed`, or is this literally just copying files?

### Deploying Templates

Run `cloudformation-seed -c my-project -i x0 -e dev -d my.domain.cld deploy`

**Dawn Note:** what do the flags do?  That ought to be explained somewhere.

### Modifying Dockerfiles

Take the dockerfiles and makefiles from the `examples` directory and massage them around to suit your needs.

**Dawn Note:** I can't find these, except for the Makefile in the KMS folder.  Am I missing something?  Also, I think that both this and the Make section could probably be their own docs.

### Modifying Makefiles

Take the dockerfiles and makefiles from the `examples` directory and massage them around to suit your needs.

## Release Management

cloudformation-seed also can read a release manifest file if you specify it in the `-m` commandline argument. Release manifest contains artifact names, their versions and other information about the software that is being deployed by the Seed. You can then inform your Cloudformation stacks about the versions and images you are deploying using the `!ArtifactVersion`, `!ArtifactRepo` and `!ArtifactImage` tags in the runtime environment configuration.

More documentation about release management is coming soon.

## Dependencies and frameworks

* [Python dependencies - placeholder]() 

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
