#!/usr/bin/env python
"""Setuptools distribution file."""
import os
import platform
from setuptools import setup


def _get_here(fname):
    return os.path.join(os.path.dirname(__file__), fname)


def _get_long_description(fname, encoding='utf8'):
    return open(fname, 'r', encoding=encoding).read()


setup(name='asynctelnet',
      # keep in sync w/docs/conf.py manually for now, please!
      url='http://asynctelnet.readthedocs.io/',
      license='ISC',
      author='Matthias Urlichs',
      description="Python 3 anyio Telnet server and client Protocol library",
      long_description=_get_long_description(fname=_get_here('README.rst')),
      packages=['asynctelnet'],
      package_data={'': ['README.rst', 'requirements.txt'], },
      entry_points={
         'console_scripts': [
             'asynctelnet-server = asynctelnet.server:main',
             'asynctelnet-client = asynctelnet.client:main'
         ]},
      author_email='matthias@urlichs.de',
      platforms='any',
      zip_safe=True,
      keywords=', '.join(('telnet', 'server', 'client', 'bbs', 'mud', 'utf8',
                          'cp437', 'api', 'library', 'anyio', 'trio', 'asyncio', 'talker')),
      classifiers=['License :: OSI Approved :: ISC License (ISCL)',
                   'Programming Language :: Python :: 3.6',
                   'Programming Language :: Python :: 3.7',
                   'Programming Language :: Python :: 3.8',
                   'Programming Language :: Python :: 3.9',
                   'Intended Audience :: Developers',
                   'Development Status :: 3 - Alpha',
                   'Topic :: System :: Networking',
                   'Topic :: Terminals :: Telnet',
                   'Topic :: System :: Shells',
                   'Topic :: Internet',
                   ],
      )
