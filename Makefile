all: sdist bdist web

sdist:
	python setup.py sdist

bdist:
	python setup.py bdist --format=rpm

web:
	pydoc -w pysysconf

install:
	python setup.py install
