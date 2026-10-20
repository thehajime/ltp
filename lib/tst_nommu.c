// SPDX-License-Identifier: GPL-2.0-or-later

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "tst_nommu.h"

int tst_is_nommu(void)
{
	static int is_nommu = -1;
	FILE *meminfo;
	char *line = NULL;
	size_t len = 0;

	if (is_nommu >= 0)
		return is_nommu;

	meminfo = fopen("/proc/meminfo", "r");
	if (!meminfo)
		return 0;

	is_nommu = 0;
	while (getline(&line, &len, meminfo) >= 0) {
		if (!strncmp(line, "MmapCopy:", sizeof("MmapCopy:") - 1)) {
			is_nommu = 1;
			break;
		}
	}

	free(line);
	fclose(meminfo);

	return is_nommu;
}
