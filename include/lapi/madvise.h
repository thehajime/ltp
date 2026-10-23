// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Copyright (C) 2026 Linux Test Project
 */

#ifndef LAPI_MADVISE_H__
#define LAPI_MADVISE_H__

#include <errno.h>

#include "lapi/mmap.h"

#ifndef MADV_NORMAL
# define MADV_NORMAL 0
#endif
#ifndef MADV_RANDOM
# define MADV_RANDOM 1
#endif
#ifndef MADV_SEQUENTIAL
# define MADV_SEQUENTIAL 2
#endif
#ifndef MADV_WILLNEED
# define MADV_WILLNEED 3
#endif
#ifndef MADV_DONTNEED
# define MADV_DONTNEED 4
#endif
#ifndef MADV_MERGEABLE
# define MADV_MERGEABLE 12
#endif

/*
 * uClibc omits madvise() on NOMMU. Tests that include this header and set
 * .needs_mmu are built for completeness but are skipped before their test
 * callbacks run on a NOMMU system.
 */
#if defined(__UCLIBC__) && !defined(__ARCH_USE_MMU__)
static inline int lapi_madvise(void *addr, size_t length, int advice)
{
	(void)addr;
	(void)length;
	(void)advice;
	errno = ENOSYS;
	return -1;
}
#define madvise lapi_madvise
#endif

#endif /* LAPI_MADVISE_H__ */
