// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef TST_NOMMU_H__
#define TST_NOMMU_H__

/**
 * tst_is_nommu() - Check whether the running kernel lacks an MMU.
 *
 * The first successful read of /proc/meminfo is cached. If procfs is not yet
 * mounted, the check returns false without caching so a later call can retry.
 *
 * Return: 1 if NOMMU is detected, 0 otherwise.
 */
int tst_is_nommu(void);

/**
 * IS_NOMMU - Check whether the running kernel lacks an MMU.
 *
 * Return: 1 if NOMMU is detected, 0 otherwise.
 */
#define IS_NOMMU() tst_is_nommu()

#endif /* TST_NOMMU_H__ */
