from setuptools import setup


def readme():
    with open('README.md') as f:
        return f.read()

setup(name='privledge',
      version='0.1',
      description='Private Permissioned Ledger',
      long_description=readme(),
      url='https://github.com/elBradford/privledge',
      author='Bradford',
      packages=['privledge'],
      install_requires=[
          'python-daemon',
          'xtermcolor',
          'pycrypto',
          'base58',
      ],
      entry_points={
          'console_scripts': ['pls=privledge.main:main'],
      },
      zip_safe=False)
