# PySysConf - library to aid in system configuration.
# Copyright (C) 2004-2009 Matthew West
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""Useful commands for system configuration.

PySysConf provides a number of useful high-level functions for doing
system configuration. These are modeled on the commands in cfengine.

Logging:

All PySysConf commands will log to stdout and syslog. The verbosity is
controlled by setting the variables pysysconf.verbosity (for stdout)
and pysysconf.syslog_verbosity (for syslog). These should be set to
LOG_NONE, LOG_ERROR, LOG_ACTION, or LOG_NO_ACTION, in increasing order
of verbosity.

Exception handling:

Internal functions (those starting with an underscore) may raise
exceptions, including the local class PySysConfError, but they will
not catch any exceptions caused by unexpected errors. Externally
visible functions (those without underscores) catch and log
EnvironmentError and PySysConfError exceptions, and let other
exceptions fall through.

"""

##############################################################################
# imports
import sys, socket, os, md5, datetime, stat, errno, pwd, grp, types, syslog

_HAVE_SELINUX_MODULE = False
try:
    import selinux
    _HAVE_SELINUX_MODULE = True
except ImportError:
    pass

##############################################################################
# logging
#    LOG_NONE       don't log anything
#    LOG_ERROR      error occured
#    LOG_ACTION     we did something (copied a file, changed a link, etc)
#    LOG_NO_ACTION  we didn't do a particular thing
LOG_NONE, LOG_ERROR, LOG_ACTION, LOG_NO_ACTION, = range(4)

verbosity = LOG_ERROR
syslog_verbosity = LOG_ACTION
syslog_priority = syslog.LOG_INFO
syslog_facility = syslog.LOG_USER

syslog.openlog("pysysconf")

##############################################################################
# internal errors
class PysysconfError(Exception):
    """Class used for all exceptions raised directly by this module."""

##############################################################################
# public functions

def log(level, message):
    """Logs the message string to stdout and syslog, if the level is below
    that of the given verbosities.

    level : integer
        Level to log at. If the current logging level is less than or equal
        to level, then the message is logged, otherwise it is discarded.

    message : string
        Message to log.

    e.g. log an error:
    >>> log(LOG_ERROR, "An error occured!")
    """
    if level <= verbosity:
        print message
    if level <= syslog_verbosity:
        syslog.syslog(syslog_priority | syslog_facility, message)

def acquire_lock(lock_name):
    """Acquires the lock referenced by the given filename by creating the
    file lock_name. The parent directory of lock_name must already exist.
    
    lock_name : string
        Filename for the lock.

    return : boolean
        Returns True if the lock was successfully acquired,
        otherwise False.

    e.g. Lock a copy operation:
    >>> acquire_lock("/var/lock/pysysconf/copylock")
    """
    try:
        fd = os.open(lock_name, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0644)
    except:
        try:
            fd = open(lock_name)
            pid = fd.read()
            fd.close()
            is_running = False
            try:
                if os.system("ps p %d" % int(pid)):
                    is_running = True
            except:
                pass
            os.unlink(lock_name)
            fd = os.open(lock_name, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0644)
        except:
            log(LOG_ERROR, "Error: unable to acquire lock "
                + lock_name)
            return False
    os.write(fd, str(os.getpid()))
    try:
        os.close(fd)
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + str(e))
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    log(LOG_ACTION, "Acquired lock " + lock_name)
    return True

def release_lock(lock_name):
    """Releases a lock acquired by acquire_lock() by deleting the file
    lock_name. An exception is thrown if the lock was not already acquired.

    lock_name : string
        Filename for the lock.

    e.g. Unlock a copy operation:
    >>> release_lock("/var/lock/pysysconf/copylock")
    """
    try:
        os.unlink(lock_name)
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + str(e))
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    log(LOG_ACTION, "Released lock " + lock_name)

def check_copy(src, dst, uid = None, gid = None,
               perm = None, umask = None, dmask = None, se_context = None,
               se_user = None, se_role = None, se_type = None,
               se_level = None, backup = True, purge = False):
    """Check the copy of a file, symlink, or directory.

    src : string
        Filename of the source file, symlink, or directory.

    dst : string
        Filename of the destination object.

    uid : string, integer, or None
        (optional: default = None)
        Username (if a string) or UID (if an int) that should own the
        dst object. In the case of a directory copy, uid will be
        applied recursively to all subdirectories and their files. If
        uid is None then the uid of dst is required to be the same as
        that of src.

    gid : string, integer, or None
        (optional: default = None)
        Groupname or GID, as for uid.

    perm : string, integer, or None
        (optional: default = None)
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the
        same value, such as 0644. If None, then the permissions
        of dst will be the same as those of src, masked by
        umask (for files) or dmask (for directories).

    umask : string, integer, or None
        (optional: default = None)
        Mask for permissions of dst for the case that dst is not a
        directory. Will be applied to perm if it is not None,
        otherwise will be applied to the permissions of src. The
        format is the same as that of perm.

    dmask : string, integer, or None
        (optional: default = None)
        Mask for permissions of dst for the case that dst is a
        directory, as for umask.

    se_context : string or None
        (optional: default = None)
        SELinux context given as a string "user:role:type:level". If
        se_context is not None then all of se_user, se_role, se_type,
        and se_level must be None. If se_context is None then the
        context of dst is not changed (except possibly by se_user,
        se_role, se_type, or se_level).

    se_user : string or None
        (optional: default = None)
        SELinux context user as a string. Cannot be specified
        simultaneously with se_context. If None, then the user
        component of the context of dst is not changed (except
        possibly by se_context).

    se_role : string or None
        (optional: default = None)
        SELinux context role as a string. Cannot be specified
        simultaneously with se_context. If None, then the role
        component of the context of dst is not changed (except
        possibly by se_context).

    se_type : string or None
        (optional: default = None)
        SELinux context type as a string. Cannot be specified
        simultaneously with se_context. If None, then the type
        component of the context of dst is not changed (except
        possibly by se_context).

    se_level : string or None
        (optional: default = None)
        SELinux context level as a string. Cannot be specified
        simultaneously with se_context. If None, then the level
        component of the context of dst is not changed (except
        possibly by se_context).

    backup : boolean
        (optional: default = True)
        Whether to backup dst if it will be overwritten.

    purge : boolean
        (optional: default = False)
        Whether to delete files in dst (if it is a directory) if
        they are not present in src.

    return : boolean
	Whether any change was made to dst.

    e.g. Check that a single file is a copy:
    >>> check_copy("main.cf.server", "/etc/sendmail/main.cf")

    e.g. Check that a directory is an exact copy, without backup:
    >>> check_copy("ppds", "/etc/cups/ppds", purge = True, backup = False)
    """
    change_made = True
    try:
        src_stat = os.lstat(src)
        src_mode = src_stat.st_mode
        if stat.S_ISREG(src_mode):
            change_made = _copy_file(src, dst, backup)
        elif stat.S_ISLNK(src_mode):
            change_made = _copy_file(src, dst, backup)
        elif stat.S_ISDIR(src_mode):
            change_made = _copy_dir(src, dst, uid, gid, perm,
                                    umask, dmask, se_context, se_user,
                                    se_role, se_type, se_level, backup, purge)
        else:
            raise PysysconfError("src " + src + " is not" \
                              " a regular file, a symlink," \
                              " or a directory")
        change_made = _chkstatsrc(src, dst, uid, gid, perm, umask, dmask,
                                  se_context, se_user, se_role, se_type, se_level) \
			or change_made
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + str(e))
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    except PysysconfError, e:
        log(LOG_ERROR, "Error: " + str(e))
    return change_made

def check_link(src, dst, uid = None, gid = None, se_context = None,
               se_user = None, se_role = None, se_type = None,
               se_level = None, backup = True):
    """Check that dst is a symlink to src.

    src : string
        Filename of the source file, symlink, or directory.

    dst : string
        Filename of the symlink.

    uid : string, integer, or None
        (optional: default = None)
        Username (if a string) or UID (if an int) that should own the
        dst object. If uid is None then the uid of dst is the default.
        
    gid : string, integer, or None
        (optional: default = None)
        Groupname or GID, as for uid.

    se_context : string or None
        (optional: default = None)
        SELinux context given as a string "user:role:type:level". If
        se_context is not None then all of se_user, se_role, se_type,
        and se_level must be None. If se_context is None then the
        context of dst is not changed (except possibly by se_user,
        se_role, se_type, or se_level).

    se_user : string or None
        (optional: default = None)
        SELinux context user as a string. Cannot be specified
        simultaneously with se_context. If None, then the user
        component of the context of dst is not changed (except
        possibly by se_context).

    se_role : string or None
        (optional: default = None)
        SELinux context role as a string. Cannot be specified
        simultaneously with se_context. If None, then the role
        component of the context of dst is not changed (except
        possibly by se_context).

    se_type : string or None
        (optional: default = None)
        SELinux context type as a string. Cannot be specified
        simultaneously with se_context. If None, then the type
        component of the context of dst is not changed (except
        possibly by se_context).

    se_level : string or None
        (optional: default = None)
        SELinux context level as a string. Cannot be specified
        simultaneously with se_context. If None, then the level
        component of the context of dst is not changed (except
        possibly by se_context).

    backup : boolean
        (optional: default = True)
        Whether to backup dst if it will be overwritten.

    return : boolean
	Whether any change was made to dst.

    e.g. Check that the link /var/spool/mail points to /net/maildir:
    >>> check_link("/net/maildir", "/var/spool/mail")
    """
    change_made = False
    try:
        dst_exists = True;
        try:
            dst_stat = os.lstat(dst)
            dst_mode = dst_stat.st_mode
        except OSError, e:
            if e.errno == errno.ENOENT:
                dst_exists = False
            else:
                raise
        need_link = True
        if dst_exists:
            if stat.S_ISLNK(dst_mode):
                if os.readlink(dst) == src:
                    need_link = False
        if need_link:
	    change_made = True
            if dst_exists:
                _remove(dst, backup)
            log(LOG_ACTION, "Symlinking " + dst + " to " + src)
            os.symlink(src, dst)
        else:
            log(LOG_NO_ACTION, dst + " is already symlinked to " + src)
        change_made = _chkstat(dst, uid, gid, None, se_context,
                               se_user, se_role, se_type, se_level) \
                         or change_made
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + str(e))
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    except PysysconfError, e:
        log(LOG_ERROR, "Error: " + str(e))
    return change_made

def check_file_exists(dst, uid = None, gid = None, perm = None,
                      se_context = None, se_user = None, se_role = None,
                      se_type = None, se_level = None, backup = True):
    """Check that the file named dst exists and has the specified
    ownership and permissions. The path to dst must already exist.

    dst : string
        Filename that must exist.

    uid : string, integer, or None
        (optional: default = None)
        Username (if a string) or UID (if an int) that should own the
        dst object. If uid is None then the uid of dst is the default.
        
    gid : string, integer, or None
        (optional: default = None)
        Groupname or GID, as for uid.

    perm : string, integer, or None
        (optional: default = None)
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the
        same value, such as 0644. If None, then the permissions
        of dst will be the default.

    se_context : string or None
        (optional: default = None)
        SELinux context given as a string "user:role:type:level". If
        se_context is not None then all of se_user, se_role, se_type,
        and se_level must be None. If se_context is None then the
        context of dst is not changed (except possibly by se_user,
        se_role, se_type, or se_level).

    se_user : string or None
        (optional: default = None)
        SELinux context user as a string. Cannot be specified
        simultaneously with se_context. If None, then the user
        component of the context of dst is not changed (except
        possibly by se_context).

    se_role : string or None
        (optional: default = None)
        SELinux context role as a string. Cannot be specified
        simultaneously with se_context. If None, then the role
        component of the context of dst is not changed (except
        possibly by se_context).

    se_type : string or None
        (optional: default = None)
        SELinux context type as a string. Cannot be specified
        simultaneously with se_context. If None, then the type
        component of the context of dst is not changed (except
        possibly by se_context).

    se_level : string or None
        (optional: default = None)
        SELinux context level as a string. Cannot be specified
        simultaneously with se_context. If None, then the level
        component of the context of dst is not changed (except
        possibly by se_context).

    backup : boolean
	(optional: default = True)
        Whether to backup dst if it will be replaced.

    return : boolean
	Whether any change was made to dst.

    e.g. Check that /etc/nologin exists and is owned by root:
    >>> check_file_exists("/etc/nologin", uid = "root")
    """
    change_made = False
    try:
        dst_exists = True;
	try:
            dst_stat = os.lstat(dst)
            dst_mode = dst_stat.st_mode
        except OSError, e:
            if e.errno == errno.ENOENT:
                dst_exists = False
            else:
                raise
        need_create = True
        if dst_exists:
            if stat.S_ISREG(dst_mode):
		need_create = False
        if need_create:
	    change_made = True
            if dst_exists:
                _remove(dst, backup)
            log(LOG_ACTION, "Creating file " + dst)
            fd = os.open(dst, os.O_CREAT)
	    os.close(fd)
        else:
            log(LOG_NO_ACTION, "File " + dst + " already exists")
        change_made = _chkstat(dst, uid, gid, perm, se_context,
                               se_user, se_role, se_type, se_level) \
                         or change_made
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + str(e))
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    except PysysconfError, e:
        log(LOG_ERROR, "Error: " + str(e))
    return change_made

def check_dir_exists(dst, uid = None, gid = None, perm = None,
                     se_context = None, se_user = None, se_role = None,
                     se_type = None, se_level = None, backup = True):
    """Check that the directory named dst exists and has the specified
    ownership and permissions. The path to dst must already exist.

    dst : string
        Directory that must exist.

    uid : string, integer, or None
        (optional: default = None)
        Username (if a string) or UID (if an int) that should own the
        dst object. If uid is None then the uid of dst is the default.
        
    gid : string, integer, or None
        (optional: default = None)
        Groupname or GID, as for uid.

    perm : string, integer, or None
        (optional: default = None)
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the
        same value, such as 0644. If None, then the permissions
        of dst will be the default.

    se_context : string or None
        (optional: default = None)
        SELinux context given as a string "user:role:type:level". If
        se_context is not None then all of se_user, se_role, se_type,
        and se_level must be None. If se_context is None then the
        context of dst is not changed (except possibly by se_user,
        se_role, se_type, or se_level).

    se_user : string or None
        (optional: default = None)
        SELinux context user as a string. Cannot be specified
        simultaneously with se_context. If None, then the user
        component of the context of dst is not changed (except
        possibly by se_context).

    se_role : string or None
        (optional: default = None)
        SELinux context role as a string. Cannot be specified
        simultaneously with se_context. If None, then the role
        component of the context of dst is not changed (except
        possibly by se_context).

    se_type : string or None
        (optional: default = None)
        SELinux context type as a string. Cannot be specified
        simultaneously with se_context. If None, then the type
        component of the context of dst is not changed (except
        possibly by se_context).

    se_level : string or None
        (optional: default = None)
        SELinux context level as a string. Cannot be specified
        simultaneously with se_context. If None, then the level
        component of the context of dst is not changed (except
        possibly by se_context).

    backup : boolean
	(optional: default = True)
        Whether to backup dst if it will be replaced.

    return : boolean
	Whether any change was made to dst.

    e.g. Check that the directory /var/pysysconf exists:
    >>> check_dir_exists("/var/pysysconf")
    """
    change_made = False
    try:
        dst_exists = True;
	try:
            dst_stat = os.lstat(dst)
            dst_mode = dst_stat.st_mode
        except OSError, e:
            if e.errno == errno.ENOENT:
                dst_exists = False
            else:
                raise
        need_create = True
        if dst_exists:
            if stat.S_ISDIR(dst_mode):
		need_create = False
        if need_create:
	    change_made = True
            if dst_exists:
                _remove(dst, backup)
            log(LOG_ACTION, "Creating directory " + dst)
	    os.mkdir(dst, 0700)
        else:
            log(LOG_NO_ACTION, "Directory " + dst + " already exists")
        change_made = _chkstat(dst, uid, gid, perm, se_context,
                               se_user, se_role, se_type, se_level) \
                         or change_made
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + str(e))
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    except PysysconfError, e:
        log(LOG_ERROR, "Error: " + str(e))
    return change_made

def check_not_exists(dst, test = None, follow_links = False, backup = False):
    """Delete dst, or files in dst that satisfy test.

    dst : string
        Directory name to remove files in.

    test : remove_test object, or None
	If None, remove dst. Otherwise, use this object to test
	whether to remove a given file or directory.

    follow_links : boolean
	(optional: default = False)
	Whether to follow links to files and directories. This can be
	dangerous if a user has write access to any of the directories
	being processed.

    backup : boolean
	(optional: default = False)
	Whether to rename objects to <filename>.<isodate> rather than
	deleting them.

    return : boolean
	Whether any change was made to dst.

    e.g. Ensure /etc/nologin does not exist:
    >>> check_not_exists("/etc/nologin")

    e.g. Ensure the entire directory /etc/cups does not exist:
    >>> check_not_exists("/etc/cups")

    e.g. Ensure the contents of /var/mail do not exist, but the /var/mail
	 dirctory itself may exist:
    >>> check_not_exists("/var/mail", test = test_true())

    e.g. Ensure all backup files older than one week do not exist:
    >>> test_one_week = test_age(age = datetime.timedelta(days = 7))
    >>> check_not_exists("/backups", test = test_one_week)
    """
    change_made = False
    try:
	if test == None:
	    dst_exists = True;
    	    try:
        	dst_stat = os.lstat(dst)
      	    except OSError, e:
        	if e.errno == errno.ENOENT:
            	    dst_exists = False
       	    	else:
            	    raise
	    if dst_exists:
		change_made = True
		_remove(dst, backup)
                log(LOG_ACTION, dst + " removed")
            else:
                log(LOG_NO_ACTION, dst + " already did not exist")
	else:
	    change_made = _remove_by_test(dst, test, follow_links, backup)
            if not change_made:
                log(LOG_NO_ACTION, dst + " did not have any removals")
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + str(e))
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    except PysysconfError, e:
        log(LOG_ERROR, "Error: " + str(e))
    return change_made

def shell_command(command):
    """Run an external command in a shell.

    command : string
        Commandline to run. Will be passed to a subshell.

    return : integer
        Returns the exit status of the command.

    e.g. Restart apache:
    >>> shell_command("/sbin/service httpd restart")
    """
    log(LOG_ACTION, "Running \"" + command + "\"")
    return os.system(command)

def check_service_enabled(service_name, needs_restart = False,
                          needs_reload = False):
    """Ensure that the given service is currently running and
    will start on boot.

    service_name : string
        Name of service to enable.

    needs_restart : boolean
        (optional: default = False)
        Whether the service should be restarted if it is already
        running.

    needs_reload : boolean
        (optional: default = False)
        Whether the service should be reloaded if it is already
        running. Is superceded by needs_restart.

    return : boolean
	Whether any change was made to the service.

    e.g. Make sure slapd is running:
    >>> check_service_enabled("ldap")
    """
    change_made = False
    if shell_command("/sbin/service " + service_name + " status > /dev/null"):
        change_made = True
        log(LOG_ACTION, "Starting " + service_name)
        shell_command("/sbin/service " + service_name + " start")
    else:
        log(LOG_NO_ACTION, service_name + " is already running")
        if needs_restart:
            change_made = True
            log(LOG_ACTION, "Restarting " + service_name)
            shell_command("/sbin/service " + service_name + " restart")
        else:
            if needs_reload:
                change_made = True
                log(LOG_ACTION, "Reloading " + service_name)
                shell_command("/sbin/service " + service_name + " reload")
    if shell_command("/sbin/chkconfig --list " + service_name \
                         + " | grep -q \":on\""):
        change_made = True
        log(LOG_ACTION, "Turning on " + service_name);
        shell_command("/sbin/chkconfig " + service_name + " on")
    else:
        log(LOG_NO_ACTION, service_name + " is already on")
    return change_made

def check_service_disabled(service_name):
    """Ensure that the given service is currently not running and
    will not start on boot.

    service_name : string
        Name of service to disable.

    return : boolean
	Whether any change was made to the service.

    e.g. Make sure apache is not running:
    >>> check_service_disabled("httpd")
    """
    change_made = False
    if not shell_command("/sbin/service " + service_name + " status"
                         + " > /dev/null"):
        change_made = True
        log(LOG_ACTION, "Stopping " + service_name);
        shell_command("/sbin/service " + service_name + " stop")
    else:
        log(LOG_NO_ACTION, service_name + " is already stopped")
    if not shell_command("/sbin/chkconfig --list " + service_name \
                         + " | grep -q \":on\""):
        change_made = True
        log(LOG_ACTION, "Turning off " + service_name);
        shell_command("/sbin/chkconfig " + service_name + " off")
    else:
        log(LOG_NO_ACTION, service_name + " is already off")
    return change_made

def check_service_status(service_name, should_be_running,
                         needs_restart = False, needs_reload = False):
    """Do either check_service_enabled, if should_be_running is
    True, or check_service_disabled, if should_be_running is False.

    service_name : string
        Name of service to disable.

    should_be_running : boolean
        Whether the service should be enabled or not.

    needs_restart : boolean
        (optional: default = False)
        Whether the service should be restarted if it is already
        running.

    needs_reload : boolean
        (optional: default = False)
        Whether the service should be reloaded if it is already
        running. Is superceded by needs_restart.

    return : boolean
	Whether any change was made to the service.

    e.g. Make sure apache is running only on webservers:
    >>> check_service_status("httpd", server_web)
    """
    if should_be_running:
        change_made = check_service_enabled(service_name, needs_restart, needs_reload)
    else:
        change_made = check_service_disabled(service_name)
    return change_made

def check_rpm_installed(rpm_name):
    """Ensure that the given rpm is installed, using yum for installation.

    rpm_name : string
        Name of rpm to install.

    return : boolean
	Whether the rpm had to be installed.

    e.g. make sure the latest version of matlab is installed:
    >>> check_rpm_installed("matlab")
    """
    change_made = False
    if shell_command("/bin/rpm -q " + rpm_name + " > /dev/null"):
        change_made = True
        log(LOG_ACTION, "Installing " + rpm_name)
        shell_command("/usr/bin/yum -e 0 -d 0 -y install " + rpm_name)
    else:
        log(LOG_NO_ACTION, rpm_name + " is already installed")
    return change_made

def check_selinux_bool(bool_name, bool_value):
    """Ensure that the given SELinux boolean has the given value.

    bool_name : string
        Name of the boolean to check.

    bool_value: boolean
        Value that the boolean must have.

    return : boolean
	Whether any change was made to the boolean status.

    e.g. make sure the webserver can access user home directories:
    >>> check_sebool("httpd_enable_homedirs", True)
    """
    change_made = False
    if bool_value == True:
        if shell_command("/usr/sbin/getsebool %s | grep -q \"%s --> on\""
                         % (bool_name, bool_name)):
            change_made = True
            log(LOG_ACTION, "Setting SELinux boolean %s to on" % bool_name)
            shell_command("/usr/sbin/setsebool -P %s 1" % bool_name)
        else:
            log(LOG_NO_ACTION, "SELinux boolean %s already set to on" % bool_name)
    else:
        if shell_command("/usr/sbin/getsebool %s | grep -q \"%s --> off\""
                         % (bool_name, bool_name)):
            change_made = True
            log(LOG_ACTION, "Setting SELinux boolean %s to off" % bool_name)
            shell_command("/usr/sbin/setsebool -P %s 0" % bool_name)
        else:
            log(LOG_NO_ACTION, "SELinux boolean %s already set to off" % bool_name)
    return change_made
            
##############################################################################
# private functions

def _copy_file(src, dst, backup, log_no_action = True):
    """Copy a regular file.

    src : string
        Filename of src file. Must exist and be a regular file.

    dst : string
        Filename of destination file. May or may not exist, and
        may or may not be a regular file.

    backup : boolean
        Whether to remove dst if it is different to src, or
        to rename dst to an object with a date/time string
        appended to its name.

    log_no_action : boolean
        (optional: default = True)
        Whether to log in the case that no action was taken (if
        log_no_action is True).

    return : boolean
        Returns True if the file was copied, otherwise False.
    """
    dst_exists = True;
    try:
        dst_stat = os.lstat(dst)
        dst_mode = dst_stat.st_mode
    except OSError, e:
        if e.errno == errno.ENOENT:
            dst_exists = False
        else:
            raise
    need_copy = True
    if dst_exists:
        if stat.S_ISREG(dst_mode):
            src_stat = os.lstat(src)
            src_mode = src_stat.st_mode
            if not stat.S_ISREG(src_mode):
                raise PyError("src " + src + " changed as we were " \
                              "watching (expected a regular file)")
            if dst_stat.st_size == src_stat.st_size:
                if _md5sum(dst) == _md5sum(src):
                    need_copy = False
    if need_copy:
        if dst_exists:
            _remove(dst, backup)
        log(LOG_ACTION, "Copying " + src + " to " + dst)
        did_copy = True
        _copy_file_data(src, dst)
    else:
        if log_no_action:
            log(LOG_NO_ACTION, dst + " is already the same as " + src)
    return need_copy

def _copy_link(src, dst, backup, log_no_action = True):
    """Copy a symlink.

    src : string
        Filename of src link. Must exist and be a symlink.

    dst : string
        Filename of destination link. May or may not exist, and
        may or may not be a symlink.

    backup : boolean
        Whether to remove dst if it is different to src, or
        to rename dst to an object with a date/time string
        appended to its name.

    log_no_action : boolean
        (optional: default = True)
        Whether to log in the case that no action was taken (if
        log_no_action is True).

    return : boolean
        Returns True if the symlink was copied, otherwise False.
    """
    dst_exists = True;
    try:
        dst_stat = os.lstat(dst)
        dst_mode = dst_stat.st_mode
    except OSError, e:
        if e.errno == errno.ENOENT:
            dst_exists = False
        else:
            raise
    src_stat = os.lstat(src)
    src_mode = src_stat.st_mode
    if not stat.S_ISLNK(src_mode):
        raise PyError("src " + src + " changed as we were " \
                      "watching (expected a symlink)")
    srclink = os.readlink(src)
    need_copy = True
    if dst_exists:
        if stat.S_ISLNK(dst_mode):
            if os.readlink(dst) == srclink:
                need_copy = False
    if need_copy:
        if dst_exists:
            _remove(dst, backup)
        log(LOG_ACTION, "Copying " + src + " to " + dst)
        os.symlink(srclink, dst)
    else:
        if log_no_action:
            log(LOG_NO_ACTION, dst + " is already the same as " + src)
    return need_copy

def _copy_dir(src, dst, uid, gid, perm, umask, dmask, se_context,
              se_user, se_role, se_type, se_level, backup, purge,
              log_no_action = True):
    """Copy a directory and all its contents.

    src : string
        Filename of the source directory.

    dst : string
        Filename of the destination directory.

    uid : string, integer, or None
        Username (if a string) or UID (if an int) that should own the
        dst object. In the case of a directory copy, uid will be
        applied recursively to all subdirectories and their files. If
        uid is None then the uid of dst is required to be the same as
        that of src.

    gid : string, integer, or None
        Groupname or GID, as for uid.

    perm : string, integer, or None
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the
        same value, such as 0644. If None, then the permissions
        of dst will be the same as those of src, masked by
        umask (for files) or dmask (for directories).

    umask : string, integer, or None
        Mask for permissions of dst for the case that dst is not a
        directory. Will be applied to perm if it is not None,
        otherwise will be applied to the permissions of src. The
        format is the same as that of perm.

    dmask : string, integer, or None
        Mask for permissions of dst for the case that dst is a
        directory, as for umask.

    se_context : string or None
        SELinux context given as a string "user:role:type:level". If
        se_context is not None then all of se_user, se_role, se_type,
        and se_level must be None. If se_context is None then the
        context of dst is not changed (except possibly by se_user,
        se_role, se_type, or se_level).

    se_user : string or None
        SELinux context user as a string. Cannot be specified
        simultaneously with se_context. If None, then the user
        component of the context of dst is not changed (except
        possibly by se_context).

    se_role : string or None
        SELinux context role as a string. Cannot be specified
        simultaneously with se_context. If None, then the role
        component of the context of dst is not changed (except
        possibly by se_context).

    se_type : string or None
        SELinux context type as a string. Cannot be specified
        simultaneously with se_context. If None, then the type
        component of the context of dst is not changed (except
        possibly by se_context).

    se_level : string or None
        SELinux context level as a string. Cannot be specified
        simultaneously with se_context. If None, then the level
        component of the context of dst is not changed (except
        possibly by se_context).

    backup : boolean
        Whether to backup dst if it will be overwritten.

    purge : boolean
        Whether to delete files in dst (if it is a directory) if
        they are not present in src.

    log_no_action : boolean
        (optional: default = True)
        Whether to log in the case that no action was taken (if
        log_no_action is True).
    """
    src_stat = os.lstat(src)
    src_mode = src_stat.st_mode
    if not stat.S_ISDIR(src_mode):
        raise PyError("src " + src + " changed as we were " \
                      "watching (expected a directory)")
    src_dir = os.listdir(src)
    dst_exists = True;
    try:
        dst_stat = os.lstat(dst)
        dst_mode = dst_stat.st_mode
    except OSError, e:
        if e.errno == errno.ENOENT:
            dst_exists = False
        else:
            raise
    if dst_exists and not stat.S_ISDIR(dst_mode):
        _remove(dst)
        dst_exists = False
    if not dst_exists:
        log(LOG_ACTION, "Copying " + src + " to " + dst)
        os.mkdir(dst)
    if _chkstatsrc(src, dst, uid, gid, perm,
                   umask, dmask, se_context,
                   se_user, se_role, se_type, se_level):
        did_copy = True
    dst_dir = os.listdir(dst)
    dst_dir.sort()
    src_dir.sort()
    dst_i = 0;
    src_i = 0;
    did_copy = False
    while True:
        if dst_i < len(dst_dir):
            dst_entry = dst_dir[dst_i]
        else:
            dst_entry = None
        if src_i < len(src_dir):
            src_entry = src_dir[src_i]
        else:
            src_entry = None
        if dst_entry == None and src_entry == None:
            break
        need_copy = False
        if src_entry:
            if dst_entry == None:
                need_copy = True
                src_i = src_i + 1
            elif src_entry < dst_entry:
                need_copy = True
                src_i = src_i + 1
            elif src_entry == dst_entry:
                need_copy = True
                src_i = src_i + 1
                dst_i = dst_i + 1
        if need_copy:
            src_file = os.path.join(src, src_entry)
            dst_file = os.path.join(dst, src_entry)
            src_entry_stat = os.lstat(src_file)
            src_entry_mode = src_entry_stat.st_mode
            if stat.S_ISREG(src_entry_mode):
                if _copy_file(src_file, dst_file, backup,
                              log_no_action = False):
                    did_copy = True
            elif stat.S_ISLNK(src_entry_mode):
                if _copy_link(src_file, dst_file, backup,
                              log_no_action = False):
                    did_copy = True
            elif stat.S_ISDIR(src_entry_mode):
                if _copy_dir(src_file, dst_file, uid, gid,
                             perm, umask, dmask, se_context,
                             se_user, se_role, se_type,
                             se_level, backup, purge,
                             log_no_action = False):
                    did_copy = True
            else:
                raise PysysconfError("src " + src + " is not" \
                                  " a regular file, a symlink," \
                                  " or a directory")
            if _chkstatsrc(src, dst, uid, gid, perm, umask, dmask,
                           se_context, se_user, se_role, se_type, se_level):
                did_copy = True
        else:
            if purge:
                dst_file = os.path.join(dst, dst_entry)
                log(LOG_ACTION, "Deleting " + dst_file)
                _remove(dst_file, backup = False)
                did_copy = True
            dst_i = dst_i + 1
    if not did_copy and log_no_action:
        log(LOG_NO_ACTION, dst + " is already the same as " + src)
    return did_copy

def _rm_tree(dst):
    """Remove the directory dst and all its contents.

    dst : string
        Name of directory to delete. Must currently exist.
    """
    dst_stat = os.lstat(dst)
    dst_mode = dst_stat.st_mode
    if stat.S_ISDIR(dst_mode):
        dst_list = os.listdir(dst)
        for f in dst_list:
            f_name = os.path.join(dst, f)
            _rm_tree(f_name)
        os.rmdir(dst)
    else:
        os.unlink(dst)

def _remove(dst, backup):
    """Remove or renames the object dst.

    dst : string
        Name of object to remove. Must currently exist. May be
        a regular file, a symlink, or a directory.

    backup : boolean
        Whether to backup the current dst to the same name
        with a date/time string appended (if backup is True)
        or to simply delete dst (if backup is False).
    """
    dst_stat = os.lstat(dst)
    dst_mode = dst_stat.st_mode
    if backup:
        d = datetime.datetime.today()
        newname = dst + "." + d.isoformat()
        os.rename(dst, newname)
    else:
        if stat.S_ISDIR(dst_mode):
            _rm_tree(dst)
        else:
            os.unlink(dst)

def _copy_file_data(src, dst):
    """Do an actual file copy from src to dst.

    src : string
        Filename to copy from. Must exist and be a regular file.

    dst : string
        Filename to copy to.
    """
    fsrc = None
    fdst = None
    try:
        fsrc = open(src, 'r')
        fdst = open(dst, 'w')
        while True:
            buf = fsrc.read(8192)
            if not buf:
                break
            fdst.write(buf)
    finally:
        if fdst:
            fdst.close()
        if fsrc:
            fsrc.close()

def _md5sum(filename):
    """Compute the MD5 sum of the given file.

    filename : string
        Name of file to compute md5 sum of.

    return : string
        Returns the MD5 sum.
    """
    f = file(filename, "rb")
    m = md5.new()
    while True:
        d = f.read(8192)
        if not d:
            break
        m.update(d)
    f.close()
    return m.digest()

def _chkstat(dst, uid, gid, perm, se_context,
             se_user, se_role, se_type, se_level):
    """Check the uid, gid, and permissions of dst.

    dst : string
        Filename of object to check.

    uid : string, integer, or None
        Username (if a string) or UID (if an int) that should
        own the dst object. If None, then the uid of dst is
        not changed.

    gid : string, integer, or None
        Groupname, GID, or None, as for uid.

    perm : string, integer, or None
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the
        same value, such as 0644. If None, then the permissions
        of dst are not changed.

    se_context : string or None
        SELinux context given as a string "user:role:type:level". If
        se_context is not None then all of se_user, se_role, se_type,
        and se_level must be None. If se_context is None then the
        context of dst is not changed (except possibly by se_user,
        se_role, se_type, or se_level).

    se_user : string or None
        SELinux context user as a string. Cannot be specified
        simultaneously with se_context. If None, then the user
        component of the context of dst is not changed (except
        possibly by se_context).

    se_role : string or None
        SELinux context role as a string. Cannot be specified
        simultaneously with se_context. If None, then the role
        component of the context of dst is not changed (except
        possibly by se_context).

    se_type : string or None
        SELinux context type as a string. Cannot be specified
        simultaneously with se_context. If None, then the type
        component of the context of dst is not changed (except
        possibly by se_context).

    se_level : string or None
        SELinux context level as a string. Cannot be specified
        simultaneously with se_context. If None, then the level
        component of the context of dst is not changed (except
        possibly by se_context).

    return : boolean
        Returns True if an attributed of dst was changed, otherwise
        False.
    """
    if (se_context != None) \
            and ((se_user != None) or (se_role != None) \
                     or (se_type != None) or (se_level != None)):
        raise PysysconfError("Cannot specify se_context"
                             " simultaneously with any of se_user,"
                             " se_role, se_type, or se_level.")
    dst_stat = os.lstat(dst)
    dst_mode = dst_stat.st_mode
    dst_uid = dst_stat.st_uid
    dst_gid = dst_stat.st_gid
    dst_perm = stat.S_IMODE(dst_mode)
    if (se_context != None) or (se_user != None) \
            or (se_role != None) or (se_type != None) \
            or (se_level != None):
        if not _HAVE_SELINUX_MODULE:
            raise PysysconfError("SELinux properties specified but"
                                 " no selinux module was imported.")
        dst_se_context = selinux.lgetfilecon(dst)[1]
        if dst_se_context == None:
            raise PysysconfError("Error getting current SELinux"
                                 " context for file %s" % dst)
    need_chown = False
    did_action = False
    if uid != None:
        if isinstance(uid, str):
            uid = pwd.getpwnam(uid)[2]
        if not isinstance(uid, int):
            raise PysysconfError("Bad uid specificiation: " + str(uid))
        if uid != dst_uid:
            need_chown = True
    else:
        uid = dst_uid
    if gid != None:
        if isinstance(gid, str):
            gid = grp.getgrnam(gid)[2]
        if not isinstance(gid, int):
            raise PysysconfError("Bad gid specificiation: " + str(uid))
        if gid != dst_gid:
            need_chown = True
    else:
        gid = dst_gid
    if need_chown:
        log(LOG_ACTION, "Changing uid of " + dst + " to (" \
            + str(uid) + ", " + str(gid) + ")")
        os.chown(dst, uid, gid)
        did_action = True
    if perm != None:
        if isinstance(perm, str):
            perm = int(perm, 8)
        if not isinstance(perm, int):
            raise PysysconfError("Bad perm specificiation: " + str(perm))
        if dst_perm != perm:
            log(LOG_ACTION, "Changing permissions of %s from %o to %o" \
				% (dst, dst_perm, perm))
            try:
                os.chmod(dst, perm)
                did_action = True
            except OSError, e:
                raise PysysconfError("Could not chmod " + dst + " to " + str(perm))
    if (se_user != None) or (se_role != None) \
            or (se_type != None) or (se_level != None):
        dst_se_context_elems = dst_se_context.split(":")
        if se_user == None:
            se_user = dst_se_context_elems[0]
        if se_role == None:
            se_role = dst_se_context_elems[1]
        if se_type == None:
            se_type = dst_se_context_elems[2]
        if se_level == None:
            se_level = ":".join(dst_se_context_elems[3:])
        se_context = ":".join([se_user, se_role, se_type, se_level])
    if se_context != None:
        if not isinstance(se_context, str):
            raise PysysconfError("Bad se_context specification: " + str(se_context))
        if dst_se_context != se_context:
            log(LOG_ACTION, "Changing SELinux context of %s from %s to %s"
                % (dst, dst_se_context, se_context))
        selinux.lsetfilecon(dst, se_context)
        did_action = True
    return did_action

def _chkstatsrc(src, dst, uid, gid, perm, umask, dmask,
                se_context, se_user, se_role, se_type, se_level):
    """Ensure that the stat data for dst matches that for src and
    change the SELinux context if specified.

    src : string
        Filename of the source file, symlink, or directory.

    dst : string
        Filename of the destination object.

    uid : string, integer, or None
        Username (if a string) or UID (if an int) that should own the
        dst object. If uid is None then the uid of dst is required to
        be the same as that of src, masked by umask (if not None).

    gid : string, integer, or None
        Groupname, GID, or None, as for uid.

    perm : string, integer, or None
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the same
        value, such as 0644. If None, then the permissions of dst will
        be the same as those of src, masked by umask (if src is a
        file) or dmask (if src is a directory).

    umask : string, integer, or None
        Mask for permissions of dst for the case that src is not a
        directory. Will be applied to perm if it is not None,
        otherwise will be applied to the permissions of src. The
        format is the same as that of perm.

    dmask : string, integer, or None
        Mask for permissions of dst for the case that src is a
        directory, as for umask.

    se_context : string or None
        SELinux context given as a string "user:role:type:level". If
        se_context is not None then all of se_user, se_role, se_type,
        and se_level must be None. If se_context is None then the
        context of dst is not changed (except possibly by se_user,
        se_role, se_type, or se_level).

    se_user : string or None
        SELinux context user as a string. Cannot be specified
        simultaneously with se_context. If None, then the user
        component of the context of dst is not changed (except
        possibly by se_context).

    se_role : string or None
        SELinux context role as a string. Cannot be specified
        simultaneously with se_context. If None, then the role
        component of the context of dst is not changed (except
        possibly by se_context).

    se_type : string or None
        SELinux context type as a string. Cannot be specified
        simultaneously with se_context. If None, then the type
        component of the context of dst is not changed (except
        possibly by se_context).

    se_level : string or None
        SELinux context level as a string. Cannot be specified
        simultaneously with se_context. If None, then the level
        component of the context of dst is not changed (except
        possibly by se_context).

    return : boolean
        Returns True if an attributed of dst was changed, otherwise
        False.
    """
    src_stat = os.lstat(src)
    src_mode = src_stat.st_mode
    src_uid = src_stat.st_uid
    src_gid = src_stat.st_gid
    src_perm = stat.S_IMODE(src_mode)
    if uid == None:
        uid = src_uid
    if gid == None:
        gid = src_gid
    if perm == None:
        if stat.S_ISDIR(src_mode):
            if dmask == None:
                perm = src_perm
            else:
                perm = src_perm & dmask
        else:
            if umask == None:
                perm = src_perm
            else:
                perm = src_perm & umask
    return _chkstat(dst, uid, gid, perm, se_context, se_user,
                    se_role, se_type, se_level)

def _remove_by_test(dst, test, follow_links = False, backup = True):
    """Delete files in dst that satisfy test.

    dst : string
        Directory name to remove files in.

    test : remove_test object
	Whether to remove a given file or directory.

    follow_links : boolean
	(optional: default = False)
	Whether to follow links to files and directories. This can be
	dangerous if a user has write access to any of the directories
	being processed.

    backup : boolean
	(optional: default = True)
	Whether to rename objects to <filename>.<isodate> rather than
	deleting them.

    return : boolean
	Whether any change was made to dst.
    """
    dst_stat = os.lstat(dst)
    dst_mode = dst_stat.st_mode
    if not stat.S_ISDIR(dst_mode):
	raise PysysconfException("A test was specified for deleting in " \
				 + dst + ", but it is not a directory")
    dst_list = os.listdir(dst)
    change_made = False
    for f in dst_list:
        f_name = os.path.join(dst, f)
	if follow_links:
	    f_stat = os.stat(f_name)
	else:
	    f_stat = os.lstat(f_name)
	f_mode = f_stat.st_mode
	if test.test(f_name, f_stat):
	    _remove(f_name, backup)
            log(LOG_ACTION, f_name + " removed")
	else:
	    if stat.S_ISDIR(f_mode):
	    	change_made = _remove_by_test(f_name, test, follow_links,
					      backup) \
			      or change_made
    return change_made

class remove_test:
    """Class that implements a test for whether a given file or
    directory should be removed.
    """
    def test(self, file_name, file_stat):
	return False

class test_true(remove_test):
    """Return True unconditionally.
    """
    def test(self, file_name, file_stat):
	return True

class test_false(remove_test):
    """Return False unconditionally.
    """
    def test(self, file_name, file_stat):
	return False

class test_age(remove_test):
    """Tests whether a file is older than a given age.
    """
    age = None
    age_type = "mtime"

    def __init__(self, age = None, age_type = "mtime"):
	self.age = age
	self.age_type = age_type

    def test(self, file_name, file_stat):
   	file_mode = file_stat.st_mode
    	if self.age_type == "mtime":
	    file_time = file_stat.st_mtime
    	elif self.age_type == "atime":
	    file_time = file_stat.st_atime
    	elif self.age_type == "ctime":
	    file_time = file_stat.st_ctime
    	else:
            raise PysysconfError("Unknown age_type " + str(self.age_type))
        file_datetime = datetime.datetime.fromtimestamp(file_time)
    	now_datetime = datetime.datetime.now()
    	file_age = now_datetime - file_datetime
    	if self.age == None or self.age < file_age:
	    return True
	else:
	    return False

class test_regexp(remove_test):
    """Tests whether a filename matches a given regexp.
    """
    regexp = None

    def __init__(self, regexp):
	self.regexp = regexp

    def test(self, file_name, file_stat):
        if self.regexp.search(file_name):
	    return True
	else:
	    return False
