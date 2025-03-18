"""
stub for invoking py2app
"""

import os
from setuptools import setup
from encrust_setup import description

setup(**description.setupOptions())
