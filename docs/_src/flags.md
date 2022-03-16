# Flags

```bash
cloudformation-seed [-h] [-c COMPONENT_NAME] -i INSTALLATION_NAME -e RUNTIME_ENVIRONMENT -d DNS_DOMAIN [-o ORG_ARN] [-m MANIFEST] [-p stack-name:VarName=value [stack-name:VarName=value ...]] [--templates-dir TEMPLATES_DIR] [--appconfig-dir APPCONFIG_DIR] [--parameters-dir PARAMETERS_DIR] [--lambda-dir LAMBDA_DIR] [--templates-prefix TEMPLATES_PREFIX] [--appconfig-prefix APPCONFIG_PREFIX] [--lambda-prefix LAMBDA_PREFIX] [-v] [--no-color] [--cleanup-lambda] [--version] {deploy,teardown}
```

## Information

### `-h`, `--help`

show this help message and exit

### `--version`

Print version number

## Configuration

### `-c`, `--component-name`

Name of the component being deployed

### `-i`, `--installation-name`

Stack name

### `-e`, `--runtime-environment`

Configuration section name

### `-d`, `--dns-domain`

DNS domain associated with this installation

### `-o`, `--org-arn`

AWS Organisation ARN to allow S3 bucket access

### `-m`, `--manifest`

S3 key of a version manifest

### `-p`, `--param-overrides`

Override template parameters, if stack-name omitted VarName is overriden for every stack

## Paths

### `--templates-dir`

Relative path to CF templates

### `--appconfig-dir`

Relative path to application configuration

### `--parameters-dir`

Relative path to parameters

### `--lambda-dir`

Relative path to Lambda function sources

## S3 prefixes

### `--templates-prefix`

S3 prefix for Cloudformation templates

### `--appconfig-prefix`

S3 prefix for application configuration

### `--lambda-prefix`

S3 prefix for Lambda function sources

## Operation parameters

### `-v`, `--verbose`

Be more verbose

### `--no-color`

Strip colors for basic terminals

### `--cleanup-lambda`

Run `make clean` after uploading Lambda functions

## Positional arguments

`deploy,teardown`: Deploy or teardown the environment