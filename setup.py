import pathlib
from setuptools import setup
import version

HERE = pathlib.Path(__file__).parent

README = (HERE / 'README.md').read_text()

setup(
    name='cloudformation-seed',
    version=version.version,
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
    packages=['deploy_stack'],
    include_package_data=True,
    install_requires=['boto3>=1.9.64', 'PyYAML>=5.1', 'colorama>=0.4.1'],
    entry_points={
        'console_scripts': [
            'cloudformation-seed=deploy_stack:main',
        ]
    },
)