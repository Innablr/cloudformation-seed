Cloudformation Seed
======
[![Build Status](https://travis-ci.org/Innablr/cloudformation-seed.svg?branch=master)](https://travis-ci.org/Innablr/cloudformation-seed)

Preface
------

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

Requirements
------

You need a Mac or a Linux machine/VM to run the Seed. Windows is not supported, but it may work on Windows too if you really want it to.

You need to have Docker on the workstation.

Every Cloudformation template you use has to have 4 mandatory parameters that will be supplied by the Seed:

1. `TemplatesS3Bucket` - the Seed will automatically create an S3 bucket and every template will have its name passed down in this parameter, so it can be made available to Lambda functions, autoscaling groups, e.t.c.
2. `InstallationName` - installation name is what makes you able to deploy your project multiple times without name clashes. Every template will have it in this parameter and you have to use it in the names of your resources to make them unique across multiple installations
3. `RuntimeEnvironment` - name of the runtime environment (read *Deployment configuration*)
4. `Route53ZoneDomain` - DNS domain associated with your deployment. The Seed doesn't require it to exist, you can use it as part of your resource naming convention

Here's a snippet you can copy and paste:

```
Parameters:
  TemplatesS3Bucket:
    Type: String
    Description: S3 Bucket with the components templates
  InstallationName:
    Type: String
    Description: Unique DNS stack installation name
  RuntimeEnvironment:
    Type: String
    Description: The runtime environment config tag
    Default: dev
  Route53ZoneDomain:
    Type: String
    Description: Route53 zone domain that represents the environment
```

Quick start
------

### First things first:

1. Create a new directory for your project
2. Copy everything from the `examples` directory to the root of the project
3. Edit `parameters/dev.yaml` to your needs
4. Add more templates with `.cf.yaml` extensions under the `cloudformation` directory and include them in `parameters/dev.yaml`

### Finally:

Authenticate to AWS using your method of choice, make sure that you have set the AWS Region you need for deployment. Run `cloudformation-seed -c my-project -i x0 -e dev -d my.domain.cld deploy`

### Optionally:

Take the dockerfiles and makefiles from the `examples` directory and massage them around to suit your needs.

Deep dive
------

### Seed bucket

The Seed will automatically create an S3 bucket for operating the deployment. The name of the bucket is derived from the installation name and project name from `Makefile.particulars`. The name of the bucket will be passed down to every Cloudformation template in your deployment as `TemplatesS3Bucket`

### Deployment configuration

The `RUNTIME_ENVIRONMENT=dev` clause in the deployment directive points to the configuration file `dev.yaml` located under the `parameters` directory.

You can have multiple runtime environments for the same project with different configuration, for example if you have *dev*, *test* and *prod* environments that reuse the same Cloudformation but need different configuration, for example VPC and subnet IDs.

A runtime environment is a YAML file that:
* defines the sequence in which the Cloudformation stacks will be deployed
* sets parameters for the Cloudformation stacks

The runtime environment contains two sections:

#### `common-parameters`

In this section you can specify Cloudformation parameters that will be picked up by every stack in the deployment as a default value (i.e. if a stack has the same parameter on it it will take precedence)

Example:

```
common-parameters:
  VpcId: vpc-00000000
```

You can use `!StackOutput` (read below) in `common-parameters` and it will work as expected.

Instead of `common-parameters` you can also use YAML anchors like this:

```
SAMLUsername: &SAML_USERNAME okta_sso

stacks:
  - name: centralservices-iam-set
    type: stackset
    template: sets/iam.cf.yaml
    parameters:
      SSMLogsLambdaS3Key: !LambdaZip ssmLogsConfig.zip
      SAMLUsername: *SAML_USERNAME
```

You can also tag your stacks/stacksets by defining your tags as a dictionary and referencing them using the YAML anchors within your stacks like this:

```
tags_a: &TAGSA
  testkey1: testvalue1
  testkey2: testvalue2

tags_b: &TAGSB
  testkey3: testvalue3

  stacks:
  - name: example-stackset-template
    type: stackset
    template: sets/example-stackset-template.cf.yaml
    rollout:
      - account: '000000000000'
    tags: *TAGA

  - name: my-project-kms-decrypt-lambda
    template: support/kms-parameters-lambda.cf.yaml
    parameters:
      LambdaSourceS3Key: !LambdaZip kmsParameters.zip
    tags: *TAGSB
```

#### `stacks`

Main configuration where you describe the Cloudformation stacks you want to deploy.

Example:

```
stacks:
  - name: in-cld-managed-zone                            # name of the CF stack, INSTALLATION_NAME will be prepended
    template: centralservices/r53-zone.cf.yaml           # CF template relative to cloudformation directory
    parameters:                                          # Parameters to the CF stack
      ManagedZoneDomainName: in.cld
      ManagingAccountArns:                               # List parameters turn into comma-separated values
        - arn:aws:iam::000000000000:root
        - arn:aws:iam::111111111111:root
        - arn:aws:iam::222222222222:root

  - name: in-cld-provisioning                            # name of CF stack, INSTALLATION_NAME will be prepended
    template: centralservices/r53-provisioning.cf.yaml   # CF template relative to cloudformation directory
    parameters:
      LambdaSourceS3Key: !LambdaZip provisionR53.zip     # points to the lambda function under src/provisionR53 (read below)
      SharedServiceR53ZoneRoleArn: !StackOutput in-cld-managed-zone.ManagedZoneCrossAccountRole    # will take the output called ManagedZoneCrossAccountRole from the above stack called in-cld-managed-zone
      Route53DomainName: !StackOutput in-cld-managed-zone.ManagedZoneDomainName
      ExportOutputs: 'false'                             # put numbers and booleans in quotes

  - name: centralservices-iam-set
    type: stackset                                       # set type to stackset
    template: sets/iam.cf.yaml
    parameters:                                          # parameters to the StackSet
      SSMLogsLambdaS3Key: !LambdaZip ssmLogsConfig.zip
      SAMLUsername: *SAML_USERNAME
      SAMLProviderName: *SAML_PROVIDER_NAME
    pilot:                                               # when StackSet is updated only update instances in these accounts
      accounts:
        - '000000000000'
    rollout:                                             # manage StackSet instances
      - account: '000000000000'
        override:                                        # parameter override
          Route53ZoneDomain: prod.innablr.lan
      - account: '111111111111'
        regions:                                         # in this account it goes into two regions
          - ap-southeast-2
          - eu-west-1
        override:
          Route53ZoneDomain: preprod.innablr.lan
      - account: '222222222222'
        override:
          Route53ZoneDomain: dev.innablr.lan
      - account: '999999999999'
        regions: []                                      # this is how you delete an instance
        override:
          Route53ZoneDomain: dontwant.innablr.lan

```

### Automated Lambda functions

If your deployment contains Lambda function they can be handled by the Seed automatically. In the `examples` directory you can find an example of a Lambda function called `kmsParameters`

1. Create a directory under `src` for your Lambda, say `kmsParameters`
2. Do the development
3. Create a `Makefile` in the directory you have created and make sure that **the default target of the Makefile produces a zip-file**, say `kmsParameters.zip`
4. In your runtime environment configuration use `!LambdaZip kmsParameters.zip` to pass the zip-file name to the CloudFormation template (see the example above)

If your Lambda function is used in a StackSet and needs to be available from other AWS accounts make sure that you give access to the Seed bucket from those accounts. Refer to the stack `bucket-policy.cf.yaml` that is included in the examples.

### Arbitrary artifacts

If you want to include any configuration objects for your software or other relatively lightweight artifacts you can create a directory called `config/<runtime_environment>` under the root of your project and anything you put in this directory will be uploaded in the Seed S3 bucket under a key called `config`.

Let's say you have `config/dev/myapp_cert.pem` and you deploy a runtime configuration called `dev`. The file will be uploaded in the bucket as `config/myapp_cert.pem`.

### Configuration tags

In the runtime environment configuration you can use the following tags in stack parameters specification:

1. `!LambdaZip kmsParameters.zip` - will pass the correct S3 key to the uploaded kmsParameters.zip, so you can use it in your Lambda resources together with `TemplatesS3Bucket`

2. `!CloudformationTemplate support/bucket-policy.cf.yaml` - works very similar to `!Lambdazip` but for Cloudformation templates. Will pass down the correct S3 key to the specified CloudFormation stack

3. `!StackOutput stack-name.OutputName` - will read the corresponding output from the specified stack and pass it down here. The stack needs to have been created above in the sequence.

4. `!ArtifactVersion`, `!ArtifactRepo` and `!ArtifactImage` - these three tags are used together with a release manifest in release management

Release management
------

`deploy_stack.py` can read a release manifest file if you specify it in the `-m` commandline argument. Release manifest contains images, their versions and other information about the software that is being deployed by the Seed. You can then inform your Cloudformation stacks about the versions and images you are deploying using the `!ArtifactVersion`, `!ArtifactRepo` and `!ArtifactImage` tags in the runtime environment configuration.

More documentation about release management is coming soon.
