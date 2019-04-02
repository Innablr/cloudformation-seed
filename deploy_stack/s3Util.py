class S3Utils(object):

    def __init__(self, **kwargs):
        self.log = kwargs.get('log', '')
        self.bucket_name = kwargs.get('bucket_name', '')
        self.session = kwargs.get('session', '')

    def delete_versioned_buckets(self):
        s3_resource = self.session.resource(service_name='s3')
        bucket = s3_resource.Bucket(self.bucket_name)
        bucket.object_versions.delete()
        bucket.delete()
