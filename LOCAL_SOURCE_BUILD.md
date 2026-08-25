# Building a branch from a local CLASS checkout

This fork adds one capability to upstream `adematti/pyclass`: a branch can be built from a
**local CLASS source tree** instead of a tarball downloaded from github. This document records
what changed, how to use it, and why it exists.

It also repoints the default `mochiclass` url at
[`willlake/mochi_class_pyclass`](https://github.com/willlake/mochi_class_pyclass) (pinned to a
commit), so that a plain `pip install .` builds mochi_class **with** the hill/valley gravity model
and no local checkout is needed. Use the local-source machinery below when you are editing the
CLASS C sources; use the default url when you only want to *run* the model. INSTALL.md is the
collaborator-facing version of the latter.

## Why

`pyclass` does not compile any CLASS source that lives in this repository. For each branch
(`base`, `mochiclass`, `axiclass`, ...) `setup.py` downloads a tarball at build time, from the
url declared in `pyclass/<branch>/_version.py`:

```python
# pyclass/mochiclass/_version.py
url = 'https://github.com/willlake/mochi_class_pyclass/archive/8102f2b.tar.gz'
```

So a modification to a local mochi_class checkout — a new gravity model, say — never reaches the
compiled extension. The upstream workflow is to push the modified CLASS to github and repoint
that url, which means a commit-push-reinstall round trip for every edit to a `.c` file.

There is a second reason, specific to `mochiclass`. The obvious fix — repoint `url` at a fork of
`mochi_class_public` — does not generally work:

* `pyclass/mochiclass/patch/Makefile` is the **CLASS 3.2.1** build: pure C, `gcc -O3 -std=gnu17`,
  `.o` objects only.
* mochi_class tracking **CLASS >= 3.3** is a C++ build: `include/parallel.h` pulls in `<atomic>`,
  `std::future` and `std::mutex`, and upstream compiles those units with
  `CPP = g++ --std=c++11` into `.opp` objects.

Handing a CLASS 3.3.x tree to this Makefile fails immediately:

```
../include/parallel.h:55:10: fatal error: atomic: No such file or directory
make: *** [Makefile:110: arrays.o] Error 1
```

Supporting CLASS 3.3.x would require porting `patch/Makefile` to the C++ build and auditing
`cclassy.pxd` for struct changes between 3.2.1 and 3.3.x. Until then, **the local source tree
must be a mochi_class v3.2.1b tree**, and changes developed against a newer mochi_class have to
be ported onto it. In practice this is cheap: the `gravity_smg/` sources have barely moved
between the two versions, and such patches tend to apply with `git apply` unchanged.

## What changed in this repository

Only `setup.py`, plus one commented-out hook in `pyclass/mochiclass/_version.py`. Nothing in
`binding.pyx`, `cclassy.pxd`, `patch/Makefile` or `depends/Makefile` was touched, and the default
behaviour — download the url — is unchanged.

| Location | Change |
| --- | --- |
| `setup.py`, `find_source(branch)` | New. Resolves the source of a branch, in order of precedence: the `PYCLASS_<BRANCH>_SOURCE` environment variable, the `source` variable of `pyclass/<branch>/_version.py`, then its `url`. `find_url` is untouched and still backs the last case. |
| `setup.py`, `pack_source(source_dir, target)` | New. Packs a local directory into `depends/tmp-class-<branch>.tar.gz`, in the layout `depends/Makefile` expects — every file under a single root directory, like a github archive. Skips `.git`, `build`, `dist`, `__pycache__`, `.ipynb_checkpoints` and `*.o`, `*.opp`, `*.a`, `*.so`, `*.pyc`. Excluding stale build artifacts matters: `depends/Makefile` unpacks straight into the build directory, and objects left over from an earlier compilation of the checkout would be taken as up-to-date and silently linked in. |
| `setup.py`, `build_class(...)` | Now dispatches on what `find_source` returned: a directory is packed, a file is copied, anything else is downloaded as before. A source with no `://` that exists as neither raises, rather than falling through to the download branch — a failed download only *skips* the branch, so a typo in a local path would otherwise produce a build silently missing that extension. The rest of the function — applying `pyclass/<branch>/patch`, then `make install` through `depends/Makefile` — is unchanged, so a local build goes through exactly the same path as a downloaded one. |
| `pyclass/mochiclass/_version.py` | Added `source = None`, with the local-directory form commented out above it, and a note that the tree must be v3.2.1b. |

## Usage

Point a branch at a local tree, either per build:

```bash
export PYCLASS_MOCHICLASS_SOURCE=~/Packages/mochi_class_pyclass
```

or persistently, by uncommenting `source` in `pyclass/mochiclass/_version.py`. Every other
branch keeps downloading its url. The build prints which source it used:

```
Packing /users/.../Packages/mochi_class_pyclass into /users/.../pyclass/depends/tmp-class-mochiclass.tar.gz.
```

A tarball path works too, and is the way to build from a source tree you do not want packed on
the fly (`PYCLASS_MOCHICLASS_SOURCE=~/somewhere/mochi_class.tar.gz`) — it must have the same
single-root-directory layout as a github archive.

## Rebuilding one branch only

A full `pip install .` rebuilds all seven CLASS variants, and
`PYCLASS_BRANCHES=mochiclass pip install .` is worse: it produces a wheel containing only the
`mochiclass` extension, so the other branches lose their compiled `binding*.so`. To rebuild a
single branch, build it in place and copy the artifacts over the installed package:

```bash
cd ~/Packages/pyclass
export PYCLASS_MOCHICLASS_SOURCE=~/Packages/mochi_class_pyclass
PYCLASS_BRANCHES=mochiclass python setup.py build_ext --inplace --force

# resolve the installed package without importing pyclass: the checkout is on sys.path here,
# and importing it from this directory would find the checkout instead of the installed copy
SP=$(python -c "import sysconfig, os; print(os.path.join(sysconfig.get_paths()['purelib'], 'pyclass'))")
cp pyclass/mochiclass/binding*.so $SP/mochiclass/
rm -rf $SP/mochiclass/data $SP/mochiclass/external
cp -r pyclass/mochiclass/data pyclass/mochiclass/external $SP/mochiclass/
```

`data/` and `external/` have to travel with the `.so`: CLASS reads its `.ini`/`.pre` files and
the HyRec tables from them at runtime. `python setup.py clean` afterwards removes the in-place
`binding.c`, `data/` and `external/` from the checkout (they are `.gitignore`d in any case).

### `--force` is not optional

Without it, a change to the CLASS sources alone produces a **silently stale extension**.
`build_class` always rebuilds `libclass.a`, but `build_ext` then decides whether to relink from
`binding.pyx` against the existing `.so` only — `libclass.a` is not among the dependencies it
tracks. With `binding.pyx` unchanged it reuses the cached `build/lib.*/binding*.so` and copies
that back in place, exiting 0 with no warning. Measured on a one-line edit to
`gravity_smg/gravity_models_smg.c`:

| | md5 of `binding*.so` | edit present |
| --- | --- | --- |
| before the edit | `5517f5be…` | – |
| `build_ext --inplace` after the edit | `5517f5be…` (unchanged) | no |
| `build_ext --inplace --force` | `9543722c…` | yes |

`python setup.py clean` first has the same effect, but throws away `build/` as well. Either way
CLASS is recompiled from scratch every time — `depends/Makefile` deletes its unpacked tree at the
end of each run — so the loop costs ~60 s regardless, and there is nothing to gain by omitting
`--force`.

## The mochiclass local tree

`~/Packages/mochi_class_pyclass` is such a tree: mochi_class v3.2.1b with the hill/valley
(No Slip Gravity, arXiv:1904.12903) `gravity_model` ported onto it. It is a git repository whose
first commit is the pristine 3.2.1b tarball, so `git log -p` shows exactly what was added on top.

It is deliberately separate from `~/Packages/mochi_class_public`, which is the CLASS v3.3.3-based
fork `willlake/mochi_class_public` where that model was originally developed and which, per the
above, this pyclass cannot compile. When a model is changed there, port the diff across:

```bash
cd ~/Packages/mochi_class_public
git diff <base> HEAD -- gravity_smg include/background.h hi_class.ini > /tmp/model.patch
cd ~/Packages/mochi_class_pyclass && git apply /tmp/model.patch
```

No change to `binding.pyx` or to `cosmoprimo/mochiclassy.py` is needed to *use* a new gravity
model: `_build_file_content` in `binding.pyx` dumps the whole parameter dictionary into the CLASS
parser without a whitelist, and `mochiclassy.py` already forwards `gravity_model`,
`parameters_smg`, `expansion_model`, `expansion_smg` and `Omega_smg` verbatim. Only new *outputs*
(exposing an smg struct field as an attribute, rather than reading it from the background table)
would require touching `cclassy.pxd` and `binding.pyx`.

## Keeping the pinned commit in sync

The pinned `url` is what a plain `pip install .` compiles, so it goes stale the moment a commit
is pushed to `mochi_class_pyclass` — and the same commit is quoted in INSTALL.md and in the
example above, which then disagree with it. `tools/sync_mochiclass_pin.py` does the bump:

```bash
cd ~/Packages/pyclass
python tools/sync_mochiclass_pin.py            # pin HEAD of ~/Packages/mochi_class_pyclass
```

It reads the current `url` out of `pyclass/mochiclass/_version.py`, resolves the source
checkout's HEAD, and rewrites *every tracked file of this repository* that mentions the old
commit — so a new document quoting the pin is picked up without editing the script. It refuses
to pin a commit that is uncommitted or not yet on a remote branch (github serves no tarball for
those; `--allow-dirty` / `--allow-unpushed` override), and after writing, it downloads the new
url to prove it resolves.

| | |
| --- | --- |
| `--check` | report only, exit 1 if the pin is stale — the form to put in CI or a `pre-commit` hook |
| `--dry-run` | print the diff, write nothing |
| `--rev <commit>` | pin something other than HEAD |
| `--source-repo <dir>` | pin a checkout other than `~/Packages/mochi_class_pyclass` (also `PYCLASS_MOCHICLASS_REPO`) |
| `--rebuild` | after bumping, run the one-branch rebuild above and copy the artifacts over the installed package. Builds **from the pinned url**, so it also proves the pin compiles; `--from-local` builds from the checkout instead |
| `--git-commit` / `--push` | commit the bump here, and push this branch |

The whole loop after editing CLASS sources is then (written out step by step, from the other
side, in `~/Packages/mochi_class_pyclass/RELEASING.md`):

```bash
cd ~/Packages/mochi_class_pyclass && git commit -am '...' && git push
cd ~/Packages/pyclass && python tools/sync_mochiclass_pin.py --rebuild --git-commit --push
```

Files *outside* this repository that mention the old commit are reported, not rewritten —
`mochi_class_pyclass/change_log.md` mentions past commits as history, and rewriting those would
falsify it.

## Getting a mochi_class change into cosmoprimo

1. Make the change in `~/Packages/mochi_class_pyclass` — or make it in
   `~/Packages/mochi_class_public` and port the diff across as above. Commit it there, so the
   next port has a base to diff against.
2. Rebuild and install, with `--force`, per *Rebuilding one branch only*. ~60 s.
3. Check the binary actually carries the change, from **outside** the pyclass checkout — from
   inside it, `import pyclass` finds the checkout, which has no compiled binding:

   ```bash
   cd /tmp && python -c "
   from pyclass import mochiclass; print(mochiclass.__file__)"   # must be under site-packages
   strings $SP/mochiclass/binding*.so | grep <something new in your change>
   ```
4. Run it. `cosmoprimo` is an editable install of `~/Packages/cosmoprimo`, so it needs nothing:

   ```python
   from cosmoprimo.fiducial import DESI
   cosmo = DESI(engine='mochiclass', Omega_Lambda=0, Omega_fld=0, Omega_smg=-1,
                gravity_model='...', parameters_smg='...',
                expansion_model='wowa', expansion_smg='...')
   ```

A useful sanity check beyond "it ran": `pyclass/tests/tests.py::test_mochiclass`, and comparing
`DESI(engine='mochiclass')` against `DESI(engine='class')` in plain LCDM — they agree to ~1e-7 in
sigma8, which catches a build that came out subtly wrong rather than merely stale.
