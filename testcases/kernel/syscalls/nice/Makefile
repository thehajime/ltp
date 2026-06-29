# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) International Business Machines  Corp., 2001

top_srcdir		?= ../../../..

nice05: CFLAGS += -pthread

ifeq ($(UCLIBC),1)
FILTER_OUT_MAKE_TARGETS += nice05
endif

include $(top_srcdir)/include/mk/testcases.mk

include $(top_srcdir)/include/mk/generic_leaf_target.mk
