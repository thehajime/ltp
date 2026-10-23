// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Copyright (C) Bull S.A. 2001
 * Copyright (c) International Business Machines  Corp., 2001
 * Copyright (c) Linux Test Project, 2003-2023
 * 07/2001 Ported by Wayne Boyer
 * 05/2002 Ported by Andre Merlier
 */

/*\
 * Test for EINVAL, EPERM, EFAULT errors.
 *
 * - setgroups() fails with EINVAL if the size exceeds the kernel
 *   supplementary group limit.
 *
 * - setgroups() fails with EPERM if the calling process is not super-user.
 *
 * - setgroups() fails with EFAULT if the list has an invalid address.
 */

#include <pwd.h>
#include <limits.h>
#include <stdlib.h>

#include "tst_test.h"
#include "compat_tst_16.h"

#define TESTUSER	"nobody"

static GID_T *glist1, *glist2, *glist3;
static struct passwd *user_info;

static struct tcase {
	int gsize;
	GID_T **glist;
	int exp_errno;
} tcases[] = {
	{0, &glist1, EINVAL},
	{1, &glist2, EPERM},
	{1, &glist3, EFAULT},
};

static void verify_setgroups(unsigned int i)
{
	struct tcase *tc = &tcases[i];

	if (tc->exp_errno == EPERM)
		SAFE_SETEUID(user_info->pw_uid);

	TST_EXP_FAIL(SETGROUPS(tc->gsize, *tc->glist), tc->exp_errno,
		     "setgroups(%d, groups_list)", tc->gsize);

	if (tc->exp_errno == EPERM)
		SAFE_SETEUID(0);
}

static void setup(void)
{
	long max_groups;

	SAFE_FILE_SCANF("/proc/sys/kernel/ngroups_max", "%ld", &max_groups);

	if (max_groups < 0 || max_groups >= INT_MAX)
		tst_brk(TBROK, "Invalid kernel ngroups_max: %ld", max_groups);
	tcases[0].gsize = max_groups + 1;
	user_info = SAFE_GETPWNAM(TESTUSER);
	glist2[0] = 42;
	glist3 = tst_get_bad_addr(NULL);
}

static struct tst_test test = {
	.test = verify_setgroups,
	.tcnt = ARRAY_SIZE(tcases),
	.bufs = (struct tst_buffers []) {
		{&glist1, .size = sizeof(GID_T) * (NGROUPS + 1)},
		{&glist2, .size = sizeof(GID_T)},
		{&user_info, .size = sizeof(struct passwd)},
		{},
	},
	.setup = setup,
	.needs_root = 1,
	.needs_mmu = 1,
};
