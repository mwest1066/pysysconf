"""Cfengine-style commands for system configuration.

PyConf provides a number of useful high-level functions for doing
system configuration. These are modeled on the commands in cfengine.

Logging:

All pyConf commands will log to stdout and syslog. The verbosity is
controlled by setting the variables pyconf.verbosity (for stdout) and
pyconf.syslog_verbosity (for syslog). These should be set to LOG_NONE,
LOG_ERROR, LOG_ACTION, or LOG_NO_ACTION, in increasing order of
verbosity.

Exception handling:

Internal functions (those starting with an underscore) may raise
exceptions, including the local class PyConfError, but they will not
catch any exceptions caused by unexpected errors. Externally visible
functions (those without underscores) catch and log EnvironmentError
and PyConfError exceptions, and let other exceptions fall through.

"""

##############################################################################
# imports
import socket, os, md5, datetime, stat, errno, pwd, grp, types

##############################################################################
# logging
#    LOG_NONE       don't log anything
#    LOG_ERROR      error occured
#    LOG_ACTION     we did something (copied a file, changed a link, etc)
#    LOG_NO_ACTION  we didn't do a particular thing
LOG_NONE, LOG_ERROR, LOG_ACTION, LOG_NO_ACTION, = range(4)

verbosity = LOG_ERROR
syslog_verbosity = LOG_ACTION

##############################################################################
# classes support
classes = []
hostname = socket.getfqdn()
classes.append(hostname)
classes.append(hostname.split('.')[0])

##############################################################################
# internal errors
class PyConfError(Exception):
    """Class used for all exceptions raised directly by this module."""
    
##############################################################################
# public functions

def log(level, info):
    """Logs the info string to stdout and syslog, if the level is below
    that of the given verbosities.

    level : integer
        Level to log at. If the current logging level is less than or equal
        to level, then the message is logged, otherwise it is discarded.

    info : string
        Message to log.

    e.g. log an error:
    >>> log(LOG_ERROR, "An error occured!")
    """
    if level <= verbosity:
        print info

def acquire_lock(lockname):
    """Acquires the lock referenced by the given filename.
    The lockname must be a file on a local (non-NFS) filesystem.
    
    lockname : string
        Filename for the lock.

    return : boolean
        Returns True if the lock was successfully acquired,
        otherwise False.

    e.g. Lock a copy operation:
    >>> acquire_lock("/var/lock/pyconf/copylock")
    """
    try:
        fd = os.open(lockname, os.O_CREAT | os.O_EXCL)
    except EnvironmentError, e:
        log(LOG_ERROR, "Error: unable to acquire lock "
            + lockname + ": " + e.strerror)
        return False
    try:
        os.close(fd)
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + e.strerror)
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    log(LOG_ACTION, "Acquired lock " + lockname)
    return True

def release_lock(lockname):
    """Releases a lock aquired by acquire_lock().

    lockname : string
        Filename for the lock.

    e.g. Unlock a copy operation:
    >>> release_lock("/var/lock/pyconf/copylock")
    """
    try:
        os.unlink(lockname)
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + e.strerror)
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    log(LOG_ACTION, "Released lock " + lockname)

def copy(src, dst, uid = None, gid = None,
         perm = None, umask = None, dmask = None, backup = True,
         purge = False):
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

    backup : boolean
        (optional: default = True)
        Whether to backup dst if it will be overwritten.

    purge : boolean
        (optional: default = False)
        Whether to delete files in dst (if it is a directory) if
        they are not present in src.

    e.g. Check that a single file is a copy:
    >>> copy("main.cf.server", "/etc/sendmail/main.cf")

    e.g. Check that a directory is an exact copy, without backup:
    >>> copy("ppds", "/etc/cups/ppds", purge = True, backup = False)
    """
    try:
        srcstat = os.lstat(src)
        srcmode = srcstat[stat.ST_MODE]
        if stat.S_ISREG(srcmode):
            _copy_file(src, dst, backup)
        elif stat.S_ISLNK(srcmode):
            _copy_file(src, dst, backup)
        elif stat.S_ISDIR(srcmode):
            _copy_dir(src, dst, uid, gid, perm,
                      umask, dmask, backup, purge)
        else:
            raise PyConfError("src " + src + " is not" \
                              " a regular file, a symlink," \
                              " or a directory")
        _chkstatsrc(src, dst, uid, gid,
                    perm, umask, dmask)
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + e.strerror)
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    except PyConfError, e:
        log(LOG_ERROR, "Error: " + e.strerror)

def link(src, dst, uid = None, gid = None, perm = None):
    """Checks that dst is a symlink to src.

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

    perm : string, integer, or None
        (optional: default = None)
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the
        same value, such as 0644. If None, then the permissions
        of dst will be the default.

    e.g. Link /var/spool/mail -> /net/maildir:
    >>> link("/net/maildir", "/var/spool/mail")
    """
    try:
        dst_exists = True;
        try:
            dst_stat = os.lstat(dst)
            dst_mode = dst_stat[stat.ST_MODE]
        except OSError, e:
            if e.errno == errno.ENOENT:
                dst_exists = False
            else:
                raise
        need_copy = True
        if dst_exists:
            if stat.S_ISLNK(dst_mode):
                if os.readlink(dst) == src:
                    need_copy = False
        if need_copy:
            if dst_exists:
                _remove(dst, backup)
            log(LOG_ACTION, "Symlinking " + dst + " to " + src)
            os.symlink(src, dst)
        else:
            log(LOG_NO_ACTION, dst + " is already symlinked to " + src)
        _chkstat(dst, uid, gid, perm)
    except EnvironmentError, e:
        if e.filename == None:
            log(LOG_ERROR, "Error: " + e.strerror)
        else:
            log(LOG_ERROR, "Error: " + e.filename + ": " + e.strerror)
    except PyConfError, e:
        log(LOG_ERROR, "Error: " + e.strerror)

def remove(dst, pattern = None, recurse = 0, age = None):
    """Checks that dst (or files in dst matching pat) does not exist.

    dst : string
        Filename or directory name to remove.

    pattern : string, or None
        (optional: default = None)
        If pattern is None, then dst itself is removed. Otherwise, dst
        is not removed and only those files inside of dst (if it is a
        directory) which match the regexp pattern are removed.

    recurse : integer
        (optional: default = 0)
        Number of directory levels to recurse if pattern is not None
        and dst is a directory. A value of 1 means to only delete
        immediate children of dst, which higher values imply deeper
        recursion. A value of 0 means no limit on depth.

    age : datetime.timedelta objecct, or None
        (optional: default = None)
        Lower bound on the age of objects which will be removed, or no
        bound if None.

    e.g. Remove /etc/nologin:
    >>> remove("/etc/nologin")

    e.g. Remove the entire directory /etc/cups:
    >>> remove("/etc/cups")

    e.g. Remove the contents of /var/mail, but do not delete the
    directory /var/mail itself:
    >>> remove("/var/mail", pattern = ".*")

    e.g. Remove all backup files older than one week:
    >>> remove("/backups", pattern = ".*", \\
               age = datetime.timedelta(days = 7))
    """

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

def enable_service(service_name):
    """Ensure that the given service is currently running and
    will start on boot.

    service_name : string
        Name of service to enable.

    e.g. Make sure slapd is running:
    >>> enable_service("ldap")
    """
    if shell_command("/sbin/service " + service_name + " status > /dev/null"):
        log(LOG_ACTION, "Starting " + service_name);
        shell_command("/sbin/service " + service_name + " start")
    else:
        log(LOG_NO_ACTION, service_name + " is already running")
    if shell_command("/sbin/chkconfig --list " + service_name \
                         + " | grep -q \":on\""):
        log(LOG_ACTION, "Turning on " + service_name);
        shell_command("/sbin/chkconfig " + service_name + " on")
    else:
        log(LOG_NO_ACTION, service_name + " is already on")

def disable_service(service_name):
    """Ensure that the given service is currently not running and
    will not start on boot.

    service_name : string
        Name of service to disable.

    e.g. Make sure apache is not running:
    >>> disable_service("httpd")
    """
    if not shell_command("/sbin/service " + service_name + " status"
                         + " > /dev/null"):
        log(LOG_ACTION, "Stopping " + service_name);
        shell_command("/sbin/service " + service_name + " stop")
    else:
        log(LOG_NO_ACTION, service_name + " is already stopped")
    if not shell_command("/sbin/chkconfig --list " + service_name \
                         + " | grep -q \":on\""):
        log(LOG_ACTION, "Turning off " + service_name);
        shell_command("/sbin/chkconfig " + service_name + " off")
    else:
        log(LOG_NO_ACTION, service_name + " is already off")

def install_rpm(rpm_name):
    """Ensure that the given rpm is installed, using yum for installation.

    rpm_name : string
        Name of rpm to install.

    e.g. make sure the latest version of matlab is installed:
    >>> install_rpm(matlab)
    """
    if shell_command("/bin/rpm -q " + rpm_name + " > /dev/null"):
        log(LOG_ACTION, "Installing " + rpm_name)
        shell_command("/usr/bin/yum -e 0 -d 0 -y install " + rpm_name)
    else:
        log(LOG_NO_ACTION, rpm_name + " is already installed")
            
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
        dst_mode = dst_stat[stat.ST_MODE]
    except OSError, e:
        if e.errno == errno.ENOENT:
            dst_exists = False
        else:
            raise
    need_copy = True
    if dst_exists:
        if stat.S_ISREG(dst_mode):
            srcstat = os.lstat(src)
            srcmode = srcstat[stat.ST_MODE]
            if not stat.S_ISREG(srcmode):
                raise PyError("src " + src + " as we were watching " \
                              "(expected a regular file)")
            if dst_stat[stat.ST_SIZE] == srcstat[stat.ST_SIZE]:
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
        dst_mode = dst_stat[stat.ST_MODE]
    except OSError, e:
        if e.errno == errno.ENOENT:
            dst_exists = False
        else:
            raise
    srcstat = os.lstat(src)
    srcmode = srcstat[stat.ST_MODE]
    if not stat.S_ISLNK(srcmode):
        raise PyError("src " + src + " as we were watching " \
                      "(expected a symlink)")
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

def _copy_dir(src, dst, uid, gid, perm,
              umask, dmask, backup, purge, log_no_action = True):
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
    src_mode = src_stat[stat.ST_MODE]
    if not stat.S_ISDIR(src_mode):
        raise PyError("src " + src + " changed as we were " \
                      "watching (expected a directory)")
    src_dir = os.listdir(src)
    dst_exists = True;
    try:
        dst_stat = os.lstat(dst)
        dst_mode = dst_stat[stat.ST_MODE]
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
        _chkstatsrc(src, dst, uid, gid, \
                                perm, umask, dmask)
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
            src_entry_mode = src_entry_stat[stat.ST_MODE]
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
                             perm, umask, dmask, backup, purge,
                             log_no_action = False):
                    did_copy = True
            else:
                raise PyConfError("src " + src + " is not" \
                                  " a regular file, a symlink," \
                                  " or a directory")
            if _chkstatsrc(src_file, dst_file,
                                       uid, gid,
                                       perm, umask, dmask):
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
    dst_mode = dst_stat[stat.ST_MODE]
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
    dst_mode = dst_stat[stat.ST_MODE]
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

def _chkstat(dst, uid = None, gid = None, perm = None):
    """Check the uid, gid, and permissions of dst.

    dst : string
        Filename of object to check.

    uid : string, integer, or None
        (optional: default = None)
        Username (if a string) or UID (if an int) that should
        own the dst object. If None, then the uid of dst is
        not changed.

    gid : string, integer, or None
        (optional: default = None)
        Groupname, GID, or None, as for uid.

    perm : string, integer, or None
        (optional: default = None)
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the
        same value, such as 0644. If None, then the permissions
        of dst are not changed.

    return : boolean
        Returns True if an attributed of dst was changed, otherwise
        False.
    """
    dst_stat = os.lstat(dst)
    dst_mode = dst_stat[stat.ST_MODE]
    dst_uid = dst_stat[stat.ST_UID]
    dst_gid = dst_stat[stat.ST_GID]
    dst_perm = stat.S_IMODE(dst_mode)
    need_chown = False
    did_action = False
    if uid != None:
        if type(uid) is types.StringType:
            uid = pwd.getpwnam(uid)[0]
        if not(type(uid) is types.IntType):
            raise PyConfError("Bad uid specificiation: " + str(uid))
        if uid != dst_uid:
            need_chown = True
    else:
        uid = dst_uid
    if gid != None:
        if type(gid) is types.StringType:
            gid = grp.getgrnam(gid)[0]
        if not(type(gid) is types.IntType):
            raise PyConfError("Bad gid specificiation: " + str(uid))
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
        if type(perm) is types.StringType:
            perm = int(perm, 8)
        if not(type(perm) is types.IntType):
            raise PyConfError("Bad perm specificiation: " + str(perm))
        if dst_perm != perm:
            log(LOG_ACTION, "Changing permissions of " + dst + " to " + "%o" % perm)
            os.chmod(dst, perm)
            did_action = True
    return did_action

def _chkstatsrc(src, dst, uid = None, gid = None,
                perm = None, umask = None, dmask = None):
    """Ensure that the stat data for dst matches that for src.

    src : string
        Filename of the source file, symlink, or directory.

    dst : string
        Filename of the destination object.

    uid : string, integer, or None
        (optional: default = None)
        Username (if a string) or UID (if an int) that should own the
        dst object. If uid is None then the uid of dst is required to
        be the same as that of src.

    gid : string, integer, or None
        (optional: default = None)
        Groupname, GID, or None, as for uid.

    perm : string, integer, or None
        (optional: default = None)
        Permissions of dst. Can be a string containing an octal
        number, such as "0644", or an integer containing the same
        value, such as 0644. If None, then the permissions of dst will
        be the same as those of src, masked by umask (if src is a
        file) or dmask (if src is a directory).

    umask : string, integer, or None
        (optional: default = None)
        Mask for permissions of dst for the case that src is not a
        directory. Will be applied to perm if it is not None,
        otherwise will be applied to the permissions of src. The
        format is the same as that of perm.

    dmask : string, integer, or None
        (optional: default = None)
        Mask for permissions of dst for the case that src is a
        directory, as for umask.
    """
    srcstat = os.lstat(src)
    srcmode = srcstat[stat.ST_MODE]
    srcuid = srcstat[stat.ST_UID]
    srcgid = srcstat[stat.ST_GID]
    srcperm = stat.S_IMODE(srcmode)
    if uid == None:
        uid = srcuid
    if gid == None:
        gid = srcgid
    if perm == None:
        if stat.S_ISDIR(srcmode):
            if dmask == None:
                perm = srcperm
            else:
                perm = srcperm & dmask
        else:
            if umask == None:
                perm = srcperm
            else:
                perm = srcperm & umask
    return _chkstat(dst, uid, gid, perm)
