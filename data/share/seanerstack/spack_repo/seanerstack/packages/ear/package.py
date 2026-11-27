# SPDX-License-Identifier: Apache-2.0
import os
import re

from spack_repo.builtin.build_systems.autotools import AutotoolsPackage

from spack.package import *


class Ear(AutotoolsPackage):
    """Energy Aware Runtime: energy monitoring and management for HPC."""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/ear"
    git = "https://gitlab.seanergys.fz-juelich.de/software/ear.git"
    seanerstack_resource = "seanergys-gitlab"

    license("EPL-2.0")

    version("main", branch="main")

    depends_on("c", type="build")
    depends_on("autoconf@2.69:", type="build")
    depends_on("automake", type="build")
    depends_on("libtool", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("mpi")
    depends_on("gsl")
    depends_on("mysql@8: +client_only")
    depends_on("curl")
    depends_on("jansson")
    depends_on("libmicrohttpd")

    # EAR's recursive Makefiles expect a build in the source directory.
    parallel = False
    force_autoreconf = True

    def patch(self):
        # EAR's MySQL probe omits the plain lib directory used by Spack.
        filter_file(
            'lib64/mysql lib/mysql lib64"',
            'lib64/mysql lib/mysql lib64 lib"',
            "m4/ac_mysql.m4",
            string=True,
        )
        # MySQL may install mysql.h directly under include rather than
        # include/mysql. Accept either layout.
        filter_file(
            'test -d "$d/include/mysql" || continue',
            ': # Both MySQL header layouts are supported',
            "m4/ac_mysql.m4", string=True,
        )
        filter_file(
            'test -f "$d/include/mysql/mysql.h" || continue',
            'test -f "$d/include/mysql/mysql.h" || '
            'test -f "$d/include/mysql.h" || continue',
            "m4/ac_mysql.m4", string=True,
        )
        # Probe a stable, exported client API rather than mysql_server_end,
        # which is not an exported symbol in all MySQL client versions.
        filter_file(
            '[AC_LANG_CALL([], mysql_server_end)]',
            '[AC_LANG_PROGRAM([[extern void *mysql_init(void *);]], '
            '[[return mysql_init(0) == 0;]])]',
            "m4/ac_mysql.m4", string=True,
        )
        filter_file(
            'DB_CFLAGS="-I$DB_DIR/include"',
            'DB_CFLAGS="-I$DB_DIR/include -I$DB_DIR/include/mysql '
            '-I$PWD/.spack-mysql-include"',
            "m4/ac_mysql.m4", string=True,
        )
        # EAR still names the pre-MySQL-8 boolean typedef in this header.
        filter_file(
            "#define ear_db_bool my_bool", "#define ear_db_bool bool",
            "src/common/database/mysql_io_functions.h", string=True,
        )
        # Upstream's OpenSSL macro otherwise treats --without-openssl as
        # an enabling request with a directory named "no".
        filter_file(
            "_x_ac_openssl_is_active=1",
            'if test "x$withval" != xno; then '
            '_x_ac_openssl_is_active=1; fi',
            "m4/ac_openssl.m4", string=True,
        )

    @run_before("configure")
    def prepare_mysql_headers(self):
        # Preserve EAR's <mysql/mysql.h> includes for flat MySQL installs.
        include = self.spec["mysql"].prefix.include
        if not os.path.isfile(join_path(include, "mysql", "mysql.h")):
            if not os.path.isfile(join_path(include, "mysql.h")):
                raise InstallError("MySQL headers not found in {0}".format(include))
            shim = join_path(self.stage.source_path, ".spack-mysql-include")
            mkdirp(shim)
            link = join_path(shim, "mysql")
            if not os.path.lexists(link):
                symlink(include, link)

    @run_after("configure")
    def verify_configuration(self):
        # configure drops a feature it cannot enable without failing: check
        # that the GPU support and the MySQL backend asked for are there.
        with open(join_path(self.stage.source_path, "Makefile")) as stream:
            contents = stream.read()
        if not re.search(r"^FEAT_GPUS\s*=\s*1\s*$", contents, re.MULTILINE):
            raise InstallError("EAR did not enable GPU support")
        if not re.search(r"^FEAT_DB_MYSQL\s*=\s*1\s*$", contents, re.MULTILINE):
            raise InstallError(
                "EAR did not enable MySQL. Inspect config.log for the MySQL "
                "client link test; refusing to build without the requested backend."
            )
        match = re.search(r"^DB_BASE\s*=\s*(\S+)", contents, re.MULTILINE)
        if not match or match.group(1) != str(self.spec["mysql"].prefix):
            raise InstallError("EAR selected a MySQL installation outside the Spack spec")

        # EAR uses DB_LDFLAGS directly instead of standard LDFLAGS. Embed
        # the selected client's library paths for execution outside Spack's
        # temporary build environment.
        rpaths = " ".join(
            "-Wl,-rpath,{0}".format(directory)
            for directory in self.spec["mysql"].libs.directories
        )
        filter_file(
            r"^DB_LDFLAGS([ \t]*=[^\n]*)$",
            r"DB_LDFLAGS\1 " + rpaths,
            join_path(self.stage.source_path, "Makefile"),
        )

    def configure_args(self):
        return [
            "--sysconfdir={0}".format(self.prefix.etc),
            "--localstatedir=/var/ear",
            "--docdir={0}/doc".format(self.prefix),
            "--with-gsl={0}".format(self.spec["gsl"].prefix),
            "--with-mysql={0}".format(self.spec["mysql"].prefix),
            "--without-freeipmi",
            "--without-openssl",
            "--without-slurm",
            "--enable-gpus",
            "--disable-avx512",
            "MPICC={0}".format(self.spec["mpi"].mpicc),
        ]

    def install(self, spec, prefix):
        make("install")
        make("etc.install")

    def setup_run_environment(self, env):
        env.set("EAR_INSTALL_PATH", self.prefix)
        env.set("EAR_ETC", self.prefix.etc)
        env.set("EAR_TMP", "/var/ear")

    def test_installed(self):
        """the commands, the daemon and the library are installed, and a command runs"""
        # eacct, ereport and edb_create are built only with the MySQL backend.
        for name in ("bin/ear-info", "bin/econtrol", "bin/eacct", "bin/ereport",
                     "sbin/eard", "sbin/edb_create"):
            path = join_path(self.prefix, name)
            assert os.path.isfile(path), f"{name} was not installed at {path}"
        assert find(self.prefix.lib, "libear*.so", recursive=False), "libear was not installed"
        # ear-info --help prints its usage and exits with 1, before it reads
        # ear.conf; that it gets there shows that its libraries are found.
        ear_info = which(join_path(self.prefix.bin, "ear-info"), required=True)
        out = ear_info("--help", output=str, error=str, fail_on_error=False)
        assert "Usage:" in out, out
