// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) Wipro Technologies Ltd, 2002. All Rights Reserved.
 * Copyright (c) 2019 Petr Vorel <petr.vorel@gmail.com>
 * Author: Saji Kumar.V.R <saji.kumar@wipro.com>
 */

#include "setdomainname.h"

#define ERRNO_DESC(x) .exp_errno = x, .errno_desc = #x

#define MAX_NAME_LENGTH _UTSNAME_DOMAIN_LENGTH - 1

struct test_case {
	char *desc;
	char *name;
	int len;
	int exp_errno;
	char *errno_desc;
} tcases[] = {
	{ "len == -1", TST_VALID_DOMAIN_NAME, -1, ERRNO_DESC(EINVAL) },
	{ "len > allowed maximum", TST_VALID_DOMAIN_NAME, MAX_NAME_LENGTH + 1, ERRNO_DESC(EINVAL) },
	{ "name == NULL", NULL, MAX_NAME_LENGTH, ERRNO_DESC(EFAULT) }
};

void verify_setdomainname(unsigned int nr)
{
	struct test_case *tcase = &tcases[nr];

	TST_EXP_FAIL(do_setdomainname(tcase->name, (size_t) tcase->len), tcase->exp_errno);
}

static struct tst_test test = {
	.tcnt = ARRAY_SIZE(tcases),
	.needs_root = 1,
	.setup = setup,
	.cleanup = cleanup,
	.test = verify_setdomainname,
	.test_variants = TEST_VARIANTS,
};
