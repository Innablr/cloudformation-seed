from typing import Any, Optional
from typing import List

from cloudformation_seed import s3_classes, util

import zipfile
import subprocess
import logging

import os
import hashlib
from colorama import Fore, Style

log = logging.getLogger('stack-deployer')


class LambdaFunction(object):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str) -> None:
        self.path: str = path
        self.s3_bucket: str = s3_bucket
        self.s3_key_prefix: str = s3_key_prefix
        self.zip_file: Optional[str] = None
        self.zip_checksum: Optional[str] = None
        self.u: Optional[s3_classes.S3Uploadable] = None

    @property
    def s3_key(self) -> str:
        return self.u.s3_key

    def find_lambda_zipfile(self) -> str:
        log.debug(f'Looking for zipfile in {self.path}')
        for xf in os.listdir(self.path):
            if xf.endswith('.zip'):
                log.debug(f'Finally {xf} looks like a zip file')
                return xf
            log.debug(f'{xf} is not a zip file')
        raise util.InvalidStackConfiguration(f'Lambda function source at {self.path} must produce a zipfile')

    def checksum_zipfile(self) -> str:
        sha1sum = hashlib.sha1()
        with zipfile.ZipFile(os.path.join(self.path, self.zip_file), 'r') as f:
            for xc in sorted([xf.CRC for xf in f.filelist]):
                sha1sum.update(xc.to_bytes((xc.bit_length() + 7) // 8, 'big') or b'\0')
        return sha1sum.hexdigest()

    def prepare(self) -> None:
        log.info(f'Running make in {Fore.GREEN}{self.path}{Style.RESET_ALL}...')
        try:
            m = subprocess.run(['make'], check=True, cwd=self.path, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, encoding='utf-8')
            log.debug('Make output will follow:')
            log.debug('-' * 64)
            log.debug(m.stdout)
            log.debug('-' * 64)
        except subprocess.CalledProcessError as e:
            log.error(f'Make failed in {self.path}, make output will follow:')
            log.error('-' * 64)
            log.error(e.stdout)
            log.error('-' * 64)
            log.error('Aborting deployment')
            raise util.DeploymentFailed(f'Make failed in {self.path}') from None
        self.zip_file = self.find_lambda_zipfile()
        self.zip_checksum = self.checksum_zipfile()
        self.u = s3_classes.S3Uploadable(os.path.join(self.path, self.zip_file), self.s3_bucket,
            f'{self.s3_key_prefix}/{self.zip_checksum}-{self.zip_file}', self.zip_checksum)

    def upload(self) -> None:
        self.u.upload()

    def cleanup(self) -> None:
        log.info(f'Running make clean in {Fore.GREEN}{self.path}{Style.RESET_ALL}...')
        subprocess.run(['make', 'clean'], cwd=self.path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class LambdaCollection(object):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str) -> None:
        self.s3_bucket: Any = s3_bucket
        self.lambdas: List[LambdaFunction] = list()
        if os.path.isdir(path):
            self.lambdas = [LambdaFunction(os.path.join(path, x), self.s3_bucket, s3_key_prefix)
                        for x in os.listdir(path) if os.access(os.path.join(path, x, 'Makefile'), os.R_OK)]

    def prepare(self) -> None:
        for x in self.lambdas:
            x.prepare()

    def upload(self) -> None:
        for x in self.lambdas:
            x.upload()

    def cleanup(self) -> None:
        for x in self.lambdas:
            x.cleanup()

    def find_lambda_key(self, zip_name) -> str:
        try:
            return [x.s3_key for x in self.lambdas if x.zip_file == zip_name].pop()
        except IndexError:
            raise util.InvalidStackConfiguration(f'Lambda function bundle {zip_name} not found') from None
