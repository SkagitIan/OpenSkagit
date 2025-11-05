#!/bin/bash
# add_swap.sh — create and enable 4 GB swap on Ubuntu/Debian

SWAPFILE=/swapfile
SIZE=4G

echo "Creating ${SIZE} swap at ${SWAPFILE}..."

# 1. Allocate the file (faster and safer than fallocate on some VPSes)
sudo dd if=/dev/zero of=$SWAPFILE bs=1M count=4096 status=progress

# 2. Secure the permissions
sudo chmod 600 $SWAPFILE

# 3. Mark as swap and enable
sudo mkswap $SWAPFILE
sudo swapon $SWAPFILE

# 4. Persist on reboot
if ! grep -q "$SWAPFILE" /etc/fstab; then
  echo "$SWAPFILE none swap sw 0 0" | sudo tee -a /etc/fstab
fi

# 5. Optional tuning for smoother performance
sudo sysctl vm.swappiness=10
sudo sysctl vm.vfs_cache_pressure=50

# make it persistent
echo "vm.swappiness=10" | sudo tee /etc/sysctl.d/99-swap.conf
echo "vm.vfs_cache_pressure=50" | sudo tee -a /etc/sysctl.d/99-swap.conf

echo "✅ Swap created and enabled."
free -h
