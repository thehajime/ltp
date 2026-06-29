# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2018 Google, Inc.

top_srcdir		?= ../../../..

ifeq ($(UCLIBC),1)
FILTER_OUT_MAKE_TARGETS += tgkill01 tgkill02 tgkill03
endif

include $(top_srcdir)/include/mk/testcases.mk

include $(top_srcdir)/include/mk/generic_leaf_target.mk

CFLAGS			+= -pthread
