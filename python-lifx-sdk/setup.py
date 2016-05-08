#!/usr/bin/env python

from setuptools import setup, find_packages

setup(
    # Project Details
    name='lifx-sdk',
    version='0.8',
    packages=['lifx'],

    # Dependencies
    install_requires=[
        'bitstruct==1.0.0',
    ],

    # Tests
    test_suite="nose.collector",
    tests_require = [
        'nose',
    ],

    # Metadata for PyPI
    description='An SDK for local LAN control of bulbs, using Python',
    author='Daniel Hall',
    author_email='python-lifx-sdk@danielhall.me',
    url='http://www.danielhall.me/',
)

