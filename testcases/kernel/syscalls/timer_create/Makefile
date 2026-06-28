# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) International Business Machines  Corp., 2001

top_srcdir		?= ../../../..

# XXX: musl doesn't have
FILTER_OUT_MAKE_TARGETS += timer_create01 timer_create03

include $(top_srcdir)/include/mk/testcases.mk

CPPFLAGS		+= -D_GNU_SOURCE -I$(abs_srcdir)/../include

LDLIBS			+= -lpthread -lrt

include $(top_srcdir)/include/mk/generic_leaf_target.mk
