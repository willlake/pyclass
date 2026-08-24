class_version = '3.2.1b'
#url = 'https://github.com/mcataneo/mochi_class_public/archive/995126c.tar.gz'
# Removes print WARNING: Currently HMcode is implemented only for Brans-Dicke.
#url = 'https://github.com/adematti/mochi_class_public/archive/v3.2.1b.tar.gz'
# adematti/mochi_class_public v3.2.1b (the line above, pristine), plus the hill/valley
# (No Slip Gravity) gravity_model of arXiv:1904.12903. Bump the commit to pick up a
# newer model; the tree must stay a v3.2.1b tree (see the note on ``source`` below).
url = 'https://github.com/willlake/mochi_class_pyclass/archive/c60748d.tar.gz'

# Local source directory (or tarball) to build instead of downloading ``url``, e.g.
# to iterate on the C code of a new gravity model. Overridden by the environment
# variable PYCLASS_MOCHICLASS_SOURCE. Must be a mochi_class v3.2.1b tree: pyclass's
# patch/Makefile is the CLASS 3.2.1 pure-C build and cannot compile CLASS >= 3.3.
# See LOCAL_SOURCE_BUILD.md at the root of this repository.
#source = '~/Packages/mochi_class_pyclass'
source = None

include = ('include', 'gravity_smg/include')  # includes relative to base class directory
