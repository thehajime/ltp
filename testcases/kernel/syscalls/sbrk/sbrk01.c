// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) 2000 Silicon Graphics, Inc.  All Rights Reserved.
 *  AUTHOR : William Roske, CO-PILOT : Dave Fenner
 * Copyright (c) 2023 SUSE LLC Avinesh Kumar <avinesh.kumar@suse.com>
 */

/*\
 * Verify that sbrk() successfully increments or decrements the program's
 * data break.
 */

#include "tst_test.h"

static struct tcase {
	long increment;
} tcases[] = {
	{0},
	{8192},
	{-8192}
};

static void run(unsigned int i)
{
	struct tcase *tc = &tcases[i];

	TST_EXP_PASS_PTR_VOID(sbrk(tc->increment),
		"sbrk(%ld) returned %p", tc->increment, TST_RET_PTR);
}

static void setup(void)
{
	void *current_break = sbrk(0);

	/* Match brk01's non-mutating libc capability probe. */
	if (current_break == (void *)-1 || brk(current_break))
		tst_brk(TCONF, "libc does not implement program-break updates");
}

static struct tst_test test = {
	.setup = setup,
	.test = run,
	.tcnt = ARRAY_SIZE(tcases),
	.needs_mmu = 1,
};
