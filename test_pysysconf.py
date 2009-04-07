#!/usr/bin/python

import pysysconf, unittest, os, stat, time, datetime

pysysconf.verbosity = pysysconf.LOG_NONE
pysysconf.syslog_verbosity = pysysconf.LOG_NONE

def rm_tree(dir_name):
	if os.path.isdir(dir_name) and not os.path.islink(dir_name):
		for dir_entry in os.listdir(dir_name):
			rm_tree(os.path.join(dir_name, dir_entry))
		os.rmdir(dir_name)
	else:
		os.unlink(dir_name)

class TestPySysConfFunctions(unittest.TestCase):

	def setUp(self):
		if not os.path.exists("test"):
			os.mkdir("test")

	def tearDown(self):
		rm_tree("test")
		pass

	def test_locking(self):
		self.failUnless(pysysconf.acquire_lock("test/lockfile"))
		self.failIf(pysysconf.acquire_lock("test/lockfile"))
		pysysconf.release_lock("test/lockfile")
		self.failUnless(pysysconf.acquire_lock("test/lockfile"))
		pysysconf.release_lock("test/lockfile")

	def test_check_file_exists(self):
		pysysconf.check_file_exists("test/testfile", perm = 0640)
		st = os.stat("test/testfile")
		self.failUnless(st.st_mode & stat.S_IFREG)
		self.failUnless(stat.S_IMODE(st.st_mode) == 0640)
		pysysconf.check_file_exists("test/testfile", perm = 0766)
		st = os.stat("test/testfile")
		self.failUnless(st.st_mode & stat.S_IFREG)
		self.failUnless(stat.S_IMODE(st.st_mode) == 0766)
		pysysconf.check_not_exists("test/testfile")
		self.failIf(os.path.exists("test/testfile"))

	def test_check_dir_exists(self):
		pysysconf.check_dir_exists("test/testdir", perm = 0755)
		st = os.stat("test/testdir")
		self.failUnless(st.st_mode & stat.S_IFDIR)
		self.failUnless(stat.S_IMODE(st.st_mode) == 0755)
		pysysconf.check_dir_exists("test/testdir", perm = 0723)
		st = os.stat("test/testdir")
		self.failUnless(st.st_mode & stat.S_IFDIR)
		self.failUnless(stat.S_IMODE(st.st_mode) == 0723)
		pysysconf.check_not_exists("test/testdir")
		self.failIf(os.path.exists("test/testdir"))

	def test_check_link(self):
		pysysconf.check_link("test/testdest", "test/testlink")
		st = os.lstat("test/testlink")
		self.failUnless(st.st_mode & stat.S_IFLNK)
		pysysconf.check_not_exists("test/testlink")
		self.failIf(os.path.exists("test/testlink"))

	def test_shell_command(self):
		self.failIf(pysysconf.shell_command("true"))
		self.failUnless(pysysconf.shell_command("false"))

	def test_check_not_exists(self):
		pysysconf.check_file_exists("test/testfile0")
		pysysconf.check_file_exists("test/testfile1")
		time.sleep(3)
		pysysconf.check_file_exists("test/testfile2")
		pysysconf.check_file_exists("test/testfile3")
		pysysconf.check_not_exists("test", test = \
				pysysconf.test_age(age = \
				datetime.timedelta(seconds = 2)))
		self.failIf(os.path.exists("test/testfile0"))
		self.failIf(os.path.exists("test/testfile1"))
		self.failUnless(os.path.exists("test/testfile2"))
		self.failUnless(os.path.exists("test/testfile3"))
		pysysconf.check_not_exists("test", test = \
				pysysconf.test_true())
		self.failIf(os.path.exists("test/testfile2"))
		self.failIf(os.path.exists("test/testfile3"))

suite = unittest.TestSuite()
suite.addTest(unittest.makeSuite(TestPySysConfFunctions))
unittest.TextTestRunner(verbosity=2).run(suite)
