#!/usr/bin/env bash
# Prune files in tree that are extraneous

if [ $(id -u) -ne 0 ]; then
    echo "Run as superuser"
    exit 1
fi

TREE=${TREE:=./tree}
TIMESTAMP=${TIMESTAMP:=202001010100}

# Prevent heavy tears by forcing relative path
TREE=./$TREE

# Main OSTree dir, is remade in the end
# If it contains kinoite files that were removed by bazzite,
# they will be retained, bloating the final image
echo Pruning files in $TREE
rm -rf $TREE/sysroot
rm -rf $TREE/ostree

# Handle files that rpm-ostree would normally remove
if [ -f $TREE/etc/passwd ]; then
    echo
    echo Appending the following passwd users to /usr/lib/passwd
    out=$(grep -v "root" $TREE/etc/passwd)
    echo "$out"
    echo "$out" >> $TREE/usr/lib/passwd
fi
if [ -f $TREE/etc/group ]; then
    echo
    echo Appending the following group entries to /usr/lib/group
    out=$(grep -v "root\|wheel" $TREE/etc/group)
    echo "$out"
    echo "$out" >> $TREE/usr/lib/group
fi

if [ -f $TREE/etc/passwd ] || [ -f $TREE/etc/group ]; then
    echo
    echo "Warning: Make sure processed users and groups are from installed programs!"
fi

# Remove passwd and group files
rm -rf $TREE/etc/passwd*
rm -rf $TREE/etc/group*

# Merge /usr/etc to /etc
# OSTree will error out if both dirs exist
# And rpm-ostree will be confused and use only one of them
# rsync -a $TREE/usr/etc/ $TREE/etc/
# rm -rf $TREE/usr/etc
rm -r $TREE/usr/etc
mv $TREE/etc $TREE/usr/etc 

# Extra files leftover from container stuff
rm -r $TREE/run/*
rm -r $TREE/var/*

# Make basic dirs
# that OSTree expects and will panic without
# (initramfs script will fail)
# https://github.com/M1cha/archlinux-ostree/

mkdir -p $TREE/sysroot
ln -s sysroot/ostree $TREE/ostree

# Deal with /boot?

# Touch files for reproducibility
echo
echo Touching files with timestamp $TIMESTAMP for reproducibility
sudo find $TREE/ -exec touch -t $TIMESTAMP -h {} + &> /dev/null
