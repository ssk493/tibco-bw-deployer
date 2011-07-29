# setup.py
from distutils.core import setup
import os
from glob import glob
import py2exe
from py2exe.build_exe import Target


deployer = Target(
    # used for the versioninfo resource
    version = '0.1a',
    name = "B/W Deploy Helper",
    copyright = "(C) 2008 YongKi Kim, Samsung Electornics",
    description = "B/W Deploy Helper",
    comments="",
    script = 'deployer.py')


setup(name='B/W Deploy Helper',
      version='0.1a',
      author='YongKi Kim',
      author_email='yongki82.kim@samsung.com',
      url='',
	  options={"py2exe":{"optimize":2}},
      console=[deployer],
      package_dir = {'': 'D:\lib'},
      packages=['sysif'] )