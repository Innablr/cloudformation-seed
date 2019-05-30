from typing import Any, Optional

from cloudformation_seed import util

import os
import hashlib
import logging

from colorama import Fore, Style
from botocore.exceptions import ClientError

log = logging.getLogger('stack-deployer')


class S3Uploadable(object):
    def __init__(self, file_path: str, s3_bucket: Any, s3_key: str, object_checksum: Optional[str] = None) -> None:
        self.file_path: str = file_path
        self.file_checksum: str = object_checksum or self.calculate_md5(self.file_path)
        self.s3_bucket: Any = s3_bucket
        self.s3_key: str = s3_key
        self.bytes: int = 0
        self.total_bytes: int = os.path.getsize(self.file_path)

    def calculate_md5(self, file_path: str) -> str:
        md5sum = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65535), b''):
                md5sum.update(chunk)
        return md5sum.hexdigest()

    def print_progress(self, current_bytes: int) -> None:
        self.bytes += current_bytes
        log.debug(f'{self.bytes} bytes out of {self.total_bytes} complete')

    def verify_existing_checksum(self) -> bool:
        etag: str = ''
        object_key: str = ''
        o = self.s3_bucket.Object(self.s3_key)
        try:
            etag = o.e_tag.strip('"')
            object_key = o.key
        except ClientError:
            log.debug(f'{self.s3_key} doesn\'t seem to exist in the bucket')
            return False
        if self.file_checksum in object_key:
            log.debug(f'Object name {self.s3_key} contains checksum {self.file_checksum}')
            return True
        if etag == self.file_checksum:
            log.debug(f'{self.s3_key} etag matches file md5sum: {self.file_checksum}')
            return True
        log.debug(f'Checksum {self.file_checksum} doesn\'t match object {object_key} etag {etag}')
        return False

    def upload(self) -> None:
        if self.verify_existing_checksum():
            log.info(f'Object in S3 is identical to {Fore.GREEN}{self.file_path}{Style.RESET_ALL}, skipping upload')
            return
        log.info(f'Uploading {Fore.GREEN}{self.file_path}{Style.RESET_ALL} '
            f'into {Fore.GREEN}{self.s3_url}{Style.RESET_ALL}')
        self.s3_bucket.upload_file(self.file_path, self.s3_key, Callback=self.print_progress)

    @property
    def s3_url(self):
        return f'{util.session.client("s3").meta.endpoint_url}/{self.s3_bucket.name}/{self.s3_key}'


class S3RecursiveUploader(util.DirectoryScanner):
    def __init__(self, path: str, s3_bucket: Any, s3_key_prefix: str) -> None:
        self.s3_bucket: Any = s3_bucket
        self.s3_key_prefix: str = s3_key_prefix
        log.info(f'Scanning files in {Fore.GREEN}{path}{Style.RESET_ALL}...')
        self.u = [S3Uploadable(f, self.s3_bucket, f'{self.s3_key_prefix}/{k}')
            for k, f in self.scan_directories(path)]

    def upload(self) -> None:
        for xu in self.u:
            xu.upload()
