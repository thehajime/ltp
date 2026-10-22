#!/bin/sh

mount -t proc proc /proc || exit 1
mount -t sysfs sysfs /sys || exit 1
mkdir -p /dev/shm /dev/pts /tmp
mount -t tmpfs -o rw,nosuid,nodev tmpfs /dev/shm || exit 1
mount -t tmpfs -o rw,nosuid,nodev tmpfs /tmp || exit 1
mount -t devpts -o mode=0620,ptmxmode=0666 devpts /dev/pts || exit 1
ln -snf pts/ptmx /dev/ptmx
chmod 666 /dev/ptmx || exit 1

for i in 0 1 2 3 4 5 6 7; do
	if [ ! -b "/dev/loop$i" ]; then
		mknod "/dev/loop$i" b 7 "$i" || exit 1
	fi
done

busybox ifconfig lo up || exit 1

export LTPROOT=/opt/ltp
export PATH=/opt/ltp/testcases/bin:/bin:/sbin:/usr/bin:/usr/sbin
export LD_LIBRARY_PATH="$LTPROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TMPDIR=/tmp
export TERM=dumb
export PS1='__KIRK_PROMPT__ '
export LTP_VIRT_OVERRIDE=uml
export LTP_DEV=/dev/loop0
unset LTP_SINGLE_FS_TYPE

stty -F /dev/console -echo 2>/dev/null || exit 1

losetup /dev/loop0 "$LTPROOT/tmp/ltp-loop.img" || exit 1

cd /opt/ltp || exit 1

if grep -Eq '(^| )kirk_guest=1( |$)' /proc/cmdline; then
	if [ ! -x /usr/bin/python3 ] || [ ! -x "$LTPROOT/kirk" ]; then
		echo "Kirk guest mode requires Python 3 and $LTPROOT/kirk" >&2
		exit 1
	fi

	suite=$(cat "$LTPROOT/tmp/kirk-in-guest-suite") || exit 1
	case "$suite" in
		''|*[!a-zA-Z0-9_.-]*)
			echo "Invalid Kirk suite name: $suite" >&2
			exit 1
			;;
	esac

	set -- /usr/bin/python3 "$LTPROOT/kirk" \
		--no-colors \
		--com shell \
		--sut default:com=shell \
		--run-suite "$suite" \
		--workers 1 \
		--exec-timeout 600 \
		--suite-timeout 19800 \
		--json-report "$LTPROOT/tmp/kirk-in-guest-report.json"
	if [ -s "$LTPROOT/tmp/kirk-in-guest-pattern" ]; then
		set -- "$@" --run-pattern "$(cat "$LTPROOT/tmp/kirk-in-guest-pattern")"
	fi

	set +e
	"$@" > "$LTPROOT/tmp/kirk-in-guest.log" 2>&1
	status=$?
	set -e
	echo "$status" > "$LTPROOT/tmp/kirk-in-guest-exit"
	sync
	poweroff -f
	exit "$status"
fi

exec /bin/sh -i
