# Installing pyclass with mochi_class + hill/valley (No Slip Gravity)

This fork of [`adematti/pyclass`](https://github.com/adematti/pyclass) builds its `mochiclass`
extension from [`willlake/mochi_class_pyclass`](https://github.com/willlake/mochi_class_pyclass)
— mochi_class v3.2.1b plus the hill/valley (No Slip Gravity) `gravity_model` of
[arXiv:1904.12903](https://arxiv.org/abs/1904.12903). Upstream pyclass builds `mochiclass` from
`adematti/mochi_class_public`, which does not have that model, so `gravity_model = hill_valley`
fails there with *could not identify gravity_theory value*.

Everything else is unchanged: same API, same `binding.pyx`, and the other six branches (`base`,
`axiclass`, `edeclass`, ...) still come from their upstream tarballs.

| | |
| --- | --- |
| pyclass fork | `https://github.com/willlake/pyclass.git`, branch **`local-source-build`** |
| CLASS source it compiles | `willlake/mochi_class_pyclass` @ `c60748d`, pinned in `pyclass/mochiclass/_version.py` |
| Needs at build time | a C compiler with OpenMP, `numpy`, `cython`, `requests`, and network access to github |

## Which case are you?

```bash
cd /tmp && python -c "from pyclass import mochiclass; print(mochiclass.__file__)"
```

* **ModuleNotFoundError** → you have no pyclass. **Case 2** below.
* **a path under `site-packages`** → you have pyclass already. **Case 1** below. To check whether
  it is already the hill/valley build:

  ```bash
  cd /tmp && python -c "
  from pyclass import mochiclass; import glob, os, subprocess
  so = glob.glob(os.path.join(os.path.dirname(mochiclass.__file__), 'binding*.so'))[0]
  print(so, 'hill_valley' in subprocess.run(['strings', so], capture_output=True, text=True).stdout)"
  ```

  `True` means the extension already carries the model and there is nothing to do.

Run everything below in the conda/virtual environment you actually use — the compiled extension
is tied to that interpreter.

## Case 1 — you already installed pyclass against the upstream (remote) mochi_class

### Option A — clean reinstall (simplest, ~5–10 min)

Rebuilds all seven CLASS variants. Do this if you are unsure about anything.

```bash
pip uninstall -y pyclass
git clone -b local-source-build https://github.com/willlake/pyclass.git
cd pyclass
pip install .
```

Then jump to *Verify*.

### Option B — rebuild only the `mochiclass` extension (~1 min)

Keeps your existing install and replaces one extension in place. Use it when reinstalling
everything is inconvenient — a slow filesystem, or an environment you would rather not disturb.

```bash
pip install numpy cython requests          # build_ext runs without build isolation
git clone -b local-source-build https://github.com/willlake/pyclass.git
cd pyclass
PYCLASS_BRANCHES=mochiclass python setup.py build_ext --inplace --force

# copy the fresh extension over the installed package
SP=$(python -c "import sysconfig, os; print(os.path.join(sysconfig.get_paths()['purelib'], 'pyclass'))")
cp pyclass/mochiclass/binding*.so $SP/mochiclass/
rm -rf $SP/mochiclass/data $SP/mochiclass/external
cp -r pyclass/mochiclass/data pyclass/mochiclass/external $SP/mochiclass/
```

`data/` and `external/` must travel with the `.so`: CLASS reads its `.ini`/`.pre` files and the
HyRec tables from them at runtime.

Two things this option assumes, and one trap:

* Your installed pyclass must be a **1.3.0-era** pyclass (`python -c "import pyclass;
  print(pyclass.__version__)"`). `binding.pyx` is untouched by this fork, so the new `.so` drops
  straight in — but only against a matching `cclassy.pxd`. If the version differs, use Option A.
* **Do not** run `PYCLASS_BRANCHES=mochiclass pip install .` instead: that produces a wheel
  containing *only* the `mochiclass` extension, and the other six branches lose their compiled
  `binding*.so`.
* `--force` is not optional. `build_ext` does not track `libclass.a` among its dependencies, so
  with `binding.pyx` unchanged it silently reuses the cached `.so` from `build/` and exits 0 with
  a stale extension.

## Case 2 — you have never installed pyclass

```bash
git clone -b local-source-build https://github.com/willlake/pyclass.git
cd pyclass
pip install .
```

That is the whole thing — no environment variables, no separate mochi_class checkout. The
`mochiclass` branch's `_version.py` already points at `willlake/mochi_class_pyclass`, and
`setup.py` downloads it, applies `pyclass/mochiclass/patch/`, and compiles `libclass.a` the same
way it does for every other branch. Expect ~5–10 min: seven CLASS builds.

Watch the log for the line

```
Downloading https://github.com/willlake/mochi_class_pyclass/archive/c60748d.tar.gz to .../depends/tmp-class-mochiclass.tar.gz.
```

If instead you see `Could not access ...; skipping branch mochiclass`, the download failed and
**the branch is silently left out of the build** — fix the network/proxy and reinstall.

If you also want `cosmoprimo`'s `engine='mochiclass'`:

```bash
pip install git+https://github.com/cosmodesi/cosmoprimo
```

## Verify

From a directory that is **not** the pyclass checkout (inside it, `import pyclass` finds the
uncompiled source tree):

```bash
cd /tmp && python -c "
from pyclass.mochiclass import ClassEngine, Background, Fourier
params = {'h': 0.6781, 'omega_b': 0.02238280, 'omega_cdm': 0.12220,
          'Omega_Lambda': 0, 'Omega_fld': 0, 'Omega_smg': -1,
          'gravity_model': 'hill_valley',
          #                 a_K,  c_M,   tau, a_t, r,  M*^2_ini
          'parameters_smg': '1e-4, -0.05, 1., 0.5, 2., 1.',
          'expansion_model': 'wowa', 'expansion_smg': '0.686, -0.9, 0.36',
          'output': 'mPk', 'P_k_max_h/Mpc': 1}
cosmo = ClassEngine(params)
print('sigma8 =', Fourier(cosmo).sigma8_m)"
```

Those are the reference values of arXiv:1904.12903: No Slip Gravity (`r = 2`) with
`c_M = -0.05`, `tau = 1`, `a_t = 0.5`, on the mirage background `w0 = -0.9`, `wa = 0.36`.

A stronger check that the build is right rather than merely present: `mochiclass` in plain LCDM
must agree with the `base` branch to ~1e-7 in sigma8.

```bash
cd /tmp && python -c "
from pyclass import base, mochiclass
params = {'h': 0.6781, 'omega_b': 0.02238280, 'omega_cdm': 0.12220, 'output': 'mPk', 'P_k_max_h/Mpc': 1}
s = [m.Fourier(m.ClassEngine(params)).sigma8_m for m in (base, mochiclass)]
print(s, 'rel. diff %.1e' % (s[1] / s[0] - 1))"
```

The upstream test suite still passes too: `python -c "from pyclass.tests.tests import
test_mochiclass; test_mochiclass()"` (it uses `gravity_model = brans dicke`, i.e. it exercises
the parts this fork did not touch).

## Using it

Directly:

```python
from pyclass.mochiclass import ClassEngine, Background, Fourier

cosmo = ClassEngine({'Omega_Lambda': 0, 'Omega_fld': 0, 'Omega_smg': -1,
                     'gravity_model': 'hill_valley',
                     'parameters_smg': '1e-4, -0.05, 1., 0.5, 2., 1.',
                     'expansion_model': 'wowa', 'expansion_smg': '0.686, -0.9, 0.36',
                     'h': 0.6781, 'omega_b': 0.02238280, 'omega_cdm': 0.12220,
                     'output': 'mPk', 'P_k_max_h/Mpc': 1})
ba = Background(cosmo)
table = ba.table()   # includes Mpl_running_smg (alpha_M), braiding_smg, M*^2_smg
```

Through cosmoprimo:

```python
from cosmoprimo.fiducial import DESI

cosmo = DESI(engine='mochiclass', Omega_Lambda=0, Omega_fld=0, Omega_smg=-1,
             gravity_model='hill_valley',
             parameters_smg='1e-4, -0.05, 1., 0.5, 2., 1.',
             expansion_model='wowa', expansion_smg='0.686, -0.9, 0.36')
```

`parameters_smg` for `hill_valley` is `alpha_K, c_M, tau, a_t, r, M*^2_ini`. Stability requires
`c_M < 0` and `tau > 0`; leave `M*^2_ini = 1` to recover GR at early times. `r = 2` is No Slip
Gravity, `r = 1` is f(R)/Brans–Dicke/chameleon. See `gravity_models/no_slip_gravity.ini` and
`doc/hill_valley_no_slip_gravity.md` in `mochi_class_pyclass`.

## Pinning a different mochi_class commit

`PYCLASS_MOCHICLASS_SOURCE` overrides the pinned url — a tarball url, a local tarball, or a local
source directory:

```bash
export PYCLASS_MOCHICLASS_SOURCE=https://github.com/willlake/mochi_class_pyclass/archive/refs/heads/main.tar.gz
# or
export PYCLASS_MOCHICLASS_SOURCE=~/Packages/mochi_class_pyclass
```

Any of these then works with the install commands above. The local-directory form is the one to
use if you are **editing the CLASS C sources** yourself — see
[LOCAL_SOURCE_BUILD.md](LOCAL_SOURCE_BUILD.md) for that workflow, including why `--force` matters
and how to port a change from a CLASS 3.3-based tree.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `could not identify gravity_theory value` at runtime | The extension is the upstream mochi_class build. Rebuild per Case 1; check with the `strings ... hill_valley` command above. |
| `include/parallel.h:55:10: fatal error: atomic: No such file or directory` | You pointed `PYCLASS_MOCHICLASS_SOURCE` at a **CLASS ≥ 3.3** tree (e.g. `willlake/mochi_class_public`). pyclass's `patch/Makefile` is the CLASS 3.2.1 pure-C build; the source must be a v3.2.1b tree. |
| `Could not access <url>; skipping branch mochiclass` | Download failed. The build continues and produces an install **without** that branch. Fix network/proxy, then reinstall. |
| `ModuleNotFoundError: No module named 'pyclass.mochiclass.binding'` | Either the branch was skipped as above, or you are running from inside the pyclass checkout. `cd` elsewhere first. |
| Build succeeds but the model is still missing | Missing `--force` on `build_ext` (Case 1 Option B), so the cached `.so` was reused. Rerun with `--force`. |
| `fatal error: omp.h` / `library not found for -lomp` on macOS | `brew install libomp llvm` and build with that clang, or `conda install -c conda-forge compilers`. |
