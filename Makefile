info:
	@echo "make dist:     Build .tar.gz. and .rpm distribution archives (remember to"
	@echo "               bump the version number in setup.py and ChangeLog first)"
	@echo "make install:  Install on current machine"

dist: sdist bdist

sdist: pysysconf.html README MANIFEST Makefile test_pysysconf.py \
	setup.py pysysconf.html
	python setup.py sdist

bdist: pysysconf.py
	python setup.py bdist --format=rpm

pysysconf.html: pysysconf.py
	pydoc -w pysysconf

install:
	python setup.py install

clean:
	rm -f *~ *.pyc
