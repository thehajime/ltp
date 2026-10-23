// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) Linux Test Project, 2006-2021
 * Copyright (c) Wipro Technologies Ltd, 2002.  All Rights Reserved.
 * Author: Aniruddha Marathe <aniruddha.marathe@wipro.com>
 */

/*\
 * Basic test of libc wrapper of reboot(2) system call.
 *
 * Test LINUX_REBOOT_CMD_CAD_ON, LINUX_REBOOT_CMD_CAD_OFF commands,
 * which do not perform reboot.
 */

#include <unistd.h>
#include <sys/reboot.h>
#include <linux/reboot.h>
#include "tst_test.h"

#define CMD_DESC(x) .cmd = x, .desc = #x

static struct tcase {
	const char *desc;
	int cmd;
} tcases[] = {
	{CMD_DESC(LINUX_REBOOT_CMD_CAD_ON)},
	{CMD_DESC(LINUX_REBOOT_CMD_CAD_OFF)},
};

static void run(unsigned int n)
{
	TEST(reboot(tcases[n].cmd));
	/* reboot_pid_ns rejects CAD commands with EINVAL. */
	if (TST_RET == -1 && TST_ERR == EINVAL)
		tst_brk(TCONF, "CAD commands unavailable (e.g. nested PID namespace)");
	if (TST_RET)
		tst_res(TFAIL | TTERRNO, "reboot(%s) failed", tcases[n].desc);
	else
		tst_res(TPASS, "reboot(%s) passed", tcases[n].desc);
}

static struct tst_test test = {
	.needs_root = 1,
	.test = run,
	.tcnt = ARRAY_SIZE(tcases),
};
