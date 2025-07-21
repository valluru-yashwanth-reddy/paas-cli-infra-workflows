from setuptools import setup, find_packages

setup(
    name='deploy-cli',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'click',
        'boto3',
        'requests',
        'GitPython',
    ],
    entry_points={
        'console_scripts': [
            # Command 1 points to your Terraform script
            'deploy-terraform = deploy_script:cli',

            # Command 2 points to your GitHub Actions script
            'deploy-github = main:cli'
        ],
    },
)
