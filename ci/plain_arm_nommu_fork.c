/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Build-only compatibility symbol for ARM NOMMU uClibc.
 *
 * LTP detects NOMMU at runtime and uses vfork()/clone() where appropriate.
 * The NOMMU uClibc toolchain does not export fork(), but common test library
 * objects still contain MMU-only references to it. Plain NOMMU execution
 * skips tests that require successful fork semantics.
 */
#include <errno.h>
#include <sys/types.h>

pid_t fork(void)
{
	errno = EINVAL;
	return -1;
}
