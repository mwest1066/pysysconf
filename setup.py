from distutils.core import setup
setup(name = "pysysconf",
      version = "0.3.6",
      description = "Python System Configuration library",
      author = "Matthew West",
      author_email = "mwest@illinois.edu",
      url = "http://lagrange.mechse.illinois.edu/mwest/pysysconf/",
      py_modules = ["pysysconf"],
      license = "GPLv2+",
      platforms = ["Linux"],
      long_description = "A collection of functions to enable simple system configurations scripts. Primarily targeted at Red Hat and Fedora Linux.",
      classifiers = [
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Operating System :: POSIX :: Linux',
        'Topic :: System :: Systems Administration',
        ],
      )
