FROM ubuntu:22.04

# -----------------------------
# Ubuntu Package Update
# -----------------------------
RUN apt update

RUN apt install -y git python3 make autoconf g++ device-tree-compiler pkg-config
RUN apt install -y qemu-utils


# ----------------
# Buildroot Build
# ----------------
WORKDIR /work-buildroot/
RUN git clone https://github.com/buildroot/buildroot.git -b 2026.05
RUN git clone --depth=1 https://github.com/thehajime/linux/ -b zpoline-nommu-v6.10
WORKDIR /work-buildroot/buildroot/
ADD ltp-add.config /root/.
RUN cat /root/ltp-add.config >> board/qemu/riscv64-virt/linux-nommu.config

ENV LINUX_OVERRIDE_SRCDIR=/work-buildroot/linux
# update when kernel version is updated
RUN cat ./configs/qemu_riscv64_nommu_virt_defconfig | sed "s/\(BR2_PACKAGE_HOST_LINUX_HEADERS_CUSTOM.*\)/#\1/" | sed "s/6\.18\.7/7\.1\.0-rc1/" > a ; mv a configs/qemu_riscv64_nommu_virt_defconfig
RUN cat ./configs/qemu_riscv64_nommu_virt_defconfig
RUN make qemu_riscv64_nommu_virt_defconfig
RUN cat .config | sed "s/2\.6/7\.1/" > a ; mv a .config
RUN apt install -y file wget cpio unzip rsync bc
ENV FORCE_UNSAFE_CONFIGURE=1
RUN make -j 10
