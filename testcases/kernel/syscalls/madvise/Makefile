# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) International Business Machines  Corp., 2001

top_srcdir		?= ../../../..

ifeq ($(UCLIBC),1)
FILTER_OUT_MAKE_TARGETS += madvise01 madvise02 madvise03 madvise04 madvise05 madvise06 madvise07 madvise08 madvise09
FILTER_OUT_MAKE_TARGETS += madvise10 madvise11 madvise12
endif

include $(top_srcdir)/include/mk/testcases.mk

include $(top_srcdir)/include/mk/generic_leaf_target.mk

madvise11: CFLAGS += -pthread
