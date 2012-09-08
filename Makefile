info:
	@echo "make sdist:    Build .tar.gz distribution archive (remember to bump the"
	@echo "               version number in setup.py and ChangeLog first)"
	@echo "make rpm_fc14: Make an RPM on Fedora 14"
	@echo "make rpm_fc17: Make an RPM on Fedora 17"
	@echo "make install:  Install on current machine"
	@echo ""
	@echo "rpm-build package must be installed for RPM builds"

dist: sdist bdist

sdist: pysysconf.html README MANIFEST.in Makefile test_pysysconf.py \
	setup.py pysysconf.html
	python setup.py sdist

rpm_fc14: pysysconf.py
	python setup.py bdist_rpm --release="1.fc14"

rpm_fc17: pysysconf.py
	python setup.py bdist_rpm --release="1.fc17"

pysysconf.html: pysysconf.py
	pydoc -w pysysconf

install:
	python setup.py install

clean:
	rm -f *~ *.pyc
