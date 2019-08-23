import pathlib
from setuptools import setup
from cloudformation_seed.version import VERSION

HERE = pathlib.Path(__file__).parent

README = (HERE / 'README.md').read_text()
REQS = (HERE / 'requirements.txt').read_text().split('\n')

setup(
    name='cloudformation-seed',
    version=VERSION,
    description='Orchestrates large Cloudformation deployments',
    long_description=README,
    long_description_content_type='text/markdown',
    url='https://github.com/Innablr/cloudformation-seed',
    author='Alex Bukharov',
    author_email='alex.bukharov@innablr.com.au',
    license='MIT',
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
    ],
    packages=['cloudformation_seed'],
    include_package_data=True,
    install_requires=REQS,
    entry_points={
        'console_scripts': [
            'cloudformation-seed=cloudformation_seed:main',
        ]
    },
)
