// SPDX-License-Identifier: GPL-2.0-or-later
/* Validate private process creation and reaping on the ARM SVM guest. */
#include <errno.h>
#include <stdio.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void)
{
	pid_t parent = getpid();
	pid_t child = fork();
	int status = 0;

	if (child < 0) {
		perror("fork");
		return 10;
	}

	if (!child)
		_exit(getpid() != parent ? 37 : 11);

	pid_t waited;
	do {
		waited = waitpid(child, &status, 0);
	} while (waited < 0 && errno == EINTR);

	if (waited != child) {
		perror("waitpid");
		return 12;
	}

	if (!WIFEXITED(status) || WEXITSTATUS(status) != 37)
		return 13;

	puts("SVM_PRIVATE_FORK_WAITPID_PASS");
	return 0;
}
