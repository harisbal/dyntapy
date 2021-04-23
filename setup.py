#  This file is part of the Traffic Assignment Package developed at KU Leuven.
#  Copyright (c) 2020 Paul Ortmann
#  License: GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007, see license.txt
#  More information at: https://gitlab.mech.kuleuven.be/ITSCreaLab
#  or contact: ITScrealab@kuleuven.be
#
#
#


import os

from setuptools import setup


# PyPI classifiers here
CLASSIFIERS = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    "Operating System :: OS Independent",
    "Intended Audience :: Science/Research",
    "Topic :: Scientific/Engineering :: Physics",
    "Topic :: Scientific/Engineering :: Mathematics",
    "Topic :: Scientific/Engineering :: Information Analysis",
    "Programming Language :: Python",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.6",
    "Programming Language :: Python :: 3.7",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
]

DESC = (
    "Macroscopic Dynamic Traffic Assignment in Python "
)


with open("requirements.txt") as f:
    INSTALL_REQUIRES = [line.strip() for line in f.readlines()]

# now call setup
setup(
    name="dtapy",
    version="0.1",
    description=DESC,
    classifiers=CLASSIFIERS,
    url="https://gitlab.kuleuven.be/ITSCreaLab/mobilitytools",
    author="Paul Ortmann",
    author_email="itscrealab@kuleuven.be",
    license="GPLv3",
    platforms="any",
    python_requires=">=3.6",
    install_requires=INSTALL_REQUIRES,
)