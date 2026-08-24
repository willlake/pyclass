#!/usr/bin/env python3
"""
Re-pin pyclass's ``mochiclass`` branch at the current commit of the local
``mochi_class_pyclass`` checkout.

``pyclass`` compiles no CLASS source of its own: for each branch it downloads the tarball
named by ``url`` in ``pyclass/<branch>/_version.py`` (see LOCAL_SOURCE_BUILD.md). So a
commit pushed to ``willlake/mochi_class_pyclass`` does not reach a plain ``pip install .``
until that url is bumped -- and the same commit is quoted in INSTALL.md and
LOCAL_SOURCE_BUILD.md, which then go stale too.

Run this after committing and pushing a change to mochi_class_pyclass::

    python tools/sync_mochiclass_pin.py                  # bump the pin, update the docs
    python tools/sync_mochiclass_pin.py --check          # exit 1 if the pin is stale (CI)
    python tools/sync_mochiclass_pin.py --dry-run        # show the diff, write nothing
    python tools/sync_mochiclass_pin.py --rebuild        # ... and rebuild/reinstall mochiclass
    python tools/sync_mochiclass_pin.py --git-commit --push   # ... and publish the bump

It rewrites *every* tracked file of the pyclass repository that mentions the currently
pinned commit, so a new doc quoting the pin is picked up without touching this script.
Untracked files (``.ipynb_checkpoints/`` copies) are left alone.
"""

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys


DEFAULT_SOURCE_REPO = '~/Packages/mochi_class_pyclass'
ARCHIVE_RE = re.compile(r'/archive/(?:refs/(?:heads|tags)/)?(?P<ref>[^/]+?)\.tar\.gz')
URL_RE = re.compile(r'^\s*url\s*=\s*[\'"](?P<url>[^\'"]+)[\'"]', re.M)
SHA_RE = re.compile(r'^[0-9a-f]{7,40}$')
REMOTE_RE = re.compile(r'^(?:git@github\.com:|(?:https|ssh)://(?:[^@]+@)?github\.com/)'
                       r'(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$')


class Failure(Exception):
    pass


def git(repo, *args, check=True):
    """Run a git command in ``repo``, return its stripped stdout."""
    proc = subprocess.run(('git', '-C', repo) + args, capture_output=True, text=True)
    if check and proc.returncode:
        raise Failure('git {} in {} failed:\n{}'.format(' '.join(args), repo, proc.stderr.strip()))
    return proc.stdout.strip()


def resolve_repo(path, what):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(os.path.join(path, '.git')):
        raise Failure('{} is not a git checkout (--{}-repo)'.format(path, what))
    return path


def github_slug(repo):
    """``owner/name`` of the github remote of ``repo``."""
    url = git(repo, 'remote', 'get-url', 'origin')
    match = REMOTE_RE.match(url)
    if match is None:
        raise Failure('cannot read a github owner/repo out of the origin url {!r} of {}'.format(url, repo))
    return '{}/{}'.format(match.group('owner'), match.group('repo'))


def pinned_url(version_file):
    """The active (uncommented) ``url`` of a branch's ``_version.py``, and the ref it pins."""
    with open(version_file) as file:
        matches = URL_RE.findall(file.read())
    if not matches:
        raise Failure('no uncommented url = ... in {}'.format(version_file))
    url = matches[-1]  # later assignments win, as in python
    match = ARCHIVE_RE.search(url)
    if match is None:
        raise Failure('the pinned url {!r} is not a github archive tarball; '
                      'nothing to bump automatically'.format(url))
    return url, match.group('ref')


def check_source_state(source_repo, sha, args):
    """Warn (or bail) if ``sha`` is not what a github tarball would actually contain."""
    dirty = git(source_repo, 'status', '--porcelain')
    if dirty:
        message = ('{} has uncommitted changes; they are NOT in the commit being pinned:\n{}'
                   .format(source_repo, dirty))
        if not args.allow_dirty:
            raise Failure(message + '\nCommit them (or pass --allow-dirty).')
        print('WARNING: ' + message, file=sys.stderr)

    git(source_repo, 'fetch', '--quiet', 'origin', check=False)  # best effort, may be offline
    remote_branches = git(source_repo, 'branch', '-r', '--contains', sha, check=False)
    if not remote_branches:
        message = ('{} is not on any remote branch of {} -- github cannot serve a tarball for it'
                   .format(sha[:12], source_repo))
        if not args.allow_unpushed:
            raise Failure(message + '\nPush it first (or pass --allow-unpushed).')
        print('WARNING: ' + message, file=sys.stderr)


def url_is_reachable(url, timeout=30):
    import urllib.error
    import urllib.request
    request = urllib.request.Request(url, method='GET')  # HEAD is not served for codeload
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1)
            return response.status == 200, 'HTTP {}'.format(response.status)
    except urllib.error.HTTPError as exc:
        return False, 'HTTP {}'.format(exc.code)
    except Exception as exc:  # offline, proxy, ssl, ...
        return None, '{}: {}'.format(type(exc).__name__, exc)


def rewrite(pyclass_repo, old_url, new_url, old_ref, new_ref):
    """Return {path: (old_text, new_text)} for every tracked file mentioning the old pin."""
    # The bare ref is replaced wherever it appears -- prose, tables, sample build logs -- but
    # only when it is a commit sha. A tag pin such as ``v3.2.1b`` also names the CLASS version
    # these docs discuss at length, and replacing it in prose would rewrite the wrong sentences.
    patterns = [old_url] + ([old_ref] if SHA_RE.match(old_ref) else [])
    listed = git(pyclass_repo, 'grep', '-l', '-I', '-F',
                 *[arg for pattern in patterns for arg in ('-e', pattern)],
                 '--', ':(exclude,glob)**/.ipynb_checkpoints/**', check=False)
    edits = {}
    for name in filter(None, listed.splitlines()):
        path = os.path.join(pyclass_repo, name)
        with open(path) as file:
            old_text = file.read()
        new_text = old_text.replace(old_url, new_url)
        if SHA_RE.match(old_ref):
            new_text = new_text.replace(old_ref, new_ref)
        if new_text != old_text:
            edits[name] = (old_text, new_text)
    return edits


def diff(name, old_text, new_text):
    return ''.join(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                        'a/' + name, 'b/' + name))


def rebuild(pyclass_repo, source, verbose=True):
    """The one-branch rebuild of LOCAL_SOURCE_BUILD.md: build in place, copy over the install."""
    env = dict(os.environ, PYCLASS_BRANCHES='mochiclass')
    if source is None:
        env.pop('PYCLASS_MOCHICLASS_SOURCE', None)  # download the freshly bumped url
    else:
        env['PYCLASS_MOCHICLASS_SOURCE'] = source
    print('Rebuilding mochiclass from {}.'.format(source or 'the pinned url'))
    # --force is not optional: build_ext does not track libclass.a and would reuse the cached .so
    subprocess.run([sys.executable, 'setup.py', 'build_ext', '--inplace', '--force'],
                   cwd=pyclass_repo, env=env, check=True,
                   stdout=None if verbose else subprocess.DEVNULL)

    import sysconfig
    installed = os.path.join(sysconfig.get_paths()['purelib'], 'pyclass', 'mochiclass')
    if not os.path.isdir(installed):
        raise Failure('no installed pyclass at {}; run a full `pip install .` instead'.format(installed))
    built = os.path.join(pyclass_repo, 'pyclass', 'mochiclass')
    import glob
    shared = glob.glob(os.path.join(built, 'binding*.so'))
    if not shared:
        raise Failure('the build produced no binding*.so in {}'.format(built))
    for path in shared:
        shutil.copy2(path, installed)
    # data/ and external/ must travel with the .so: CLASS reads its .ini/.pre files and the
    # HyRec tables from them at runtime
    for sub in ('data', 'external'):
        target = os.path.join(installed, sub)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(os.path.join(built, sub), target)
    print('Installed {} into {}.'.format(', '.join(os.path.basename(p) for p in shared), installed))
    return installed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source-repo', default=os.getenv('PYCLASS_MOCHICLASS_REPO', DEFAULT_SOURCE_REPO),
                        help='mochi_class checkout to pin (default: %(default)s)')
    parser.add_argument('--pyclass-repo', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'),
                        help='pyclass checkout to update (default: the one holding this script)')
    parser.add_argument('--branch', default='mochiclass', help='pyclass branch to re-pin (default: %(default)s)')
    parser.add_argument('--rev', default='HEAD', help='commit of the source repo to pin (default: %(default)s)')
    parser.add_argument('--check', action='store_true', help='report only; exit 1 if the pin is stale')
    parser.add_argument('--dry-run', action='store_true', help='show the diff, write nothing')
    parser.add_argument('--allow-dirty', action='store_true', help='pin even with uncommitted changes in the source repo')
    parser.add_argument('--allow-unpushed', action='store_true', help='pin a commit that is not on any remote branch')
    parser.add_argument('--no-verify-url', action='store_true', help='skip the download check of the new url')
    parser.add_argument('--rebuild', action='store_true', help='rebuild the mochiclass extension and copy it over the installed package')
    parser.add_argument('--from-local', action='store_true', help='with --rebuild, build from the local checkout instead of the pinned url')
    parser.add_argument('--git-commit', action='store_true', help='commit the bump in the pyclass repo')
    parser.add_argument('--push', action='store_true', help='push the pyclass branch (implies --git-commit)')
    args = parser.parse_args(argv)

    source_repo = resolve_repo(args.source_repo, 'source')
    pyclass_repo = resolve_repo(args.pyclass_repo, 'pyclass')
    version_file = os.path.join(pyclass_repo, 'pyclass', args.branch, '_version.py')
    if not os.path.isfile(version_file):
        raise Failure('no such branch: {} does not exist'.format(version_file))

    full_sha = git(source_repo, 'rev-parse', '--verify', args.rev + '^{commit}')
    new_ref = git(source_repo, 'rev-parse', '--short', full_sha)
    subject = git(source_repo, 'log', '-1', '--format=%s', full_sha)
    old_url, old_ref = pinned_url(version_file)
    slug = github_slug(source_repo)
    new_url = 'https://github.com/{}/archive/{}.tar.gz'.format(slug, new_ref)

    print('pinned:  {}'.format(old_url))
    print('current: {}  ({})'.format(new_url, subject))

    if new_url == old_url and not rewrite(pyclass_repo, old_url, new_url, old_ref, new_ref):
        print('Already up to date.')
        # --rebuild is still honoured: `sync --rebuild` is the one-liner of the workflow, and
        # the extension can be stale even when the pin is not
        if args.rebuild and not (args.check or args.dry_run):
            rebuild(pyclass_repo, source_repo if args.from_local else None)
        return 0

    if not args.check:
        check_source_state(source_repo, full_sha, args)

    edits = rewrite(pyclass_repo, old_url, new_url, old_ref, new_ref)
    if not edits:
        raise Failure('the pin is stale but no tracked file mentions {!r}; '
                      'is {} the right checkout?'.format(old_ref, pyclass_repo))

    if args.check:
        print('\nStale, {} file(s) would change:'.format(len(edits)))
        for name in edits:
            print('  {}'.format(name))
        return 1

    for name, (old_text, new_text) in edits.items():
        if args.dry_run:
            sys.stdout.write(diff(name, old_text, new_text))
        else:
            with open(os.path.join(pyclass_repo, name), 'w') as file:
                file.write(new_text)
    print('\n{} {} file(s): {}'.format('Would update' if args.dry_run else 'Updated',
                                       len(edits), ', '.join(edits)))
    if args.dry_run:
        return 0

    if not args.no_verify_url:
        ok, detail = url_is_reachable(new_url)
        if ok:
            print('Verified {} is downloadable.'.format(new_url))
        elif ok is None:
            print('WARNING: could not check {} ({}).'.format(new_url, detail), file=sys.stderr)
        else:
            raise Failure('{} is not downloadable ({}). The files were updated; fix the push, '
                          'or re-run with --rev pointing at a commit github has.'.format(new_url, detail))

    # anything outside the pyclass repo that still quotes the old pin is the user's call
    for other in (source_repo,):
        mentions = git(other, 'grep', '-l', '-I', '-F', old_ref, check=False)
        for name in filter(None, mentions.splitlines()):
            print('NOTE: {} still mentions {} -- update it by hand if it is not a historical record.'
                  .format(os.path.join(os.path.basename(other), name), old_ref))

    if args.rebuild:
        rebuild(pyclass_repo, source_repo if args.from_local else None)

    if args.git_commit or args.push:
        git(pyclass_repo, 'add', '--', *edits)
        message = 'Pin mochiclass at {}@{} ({})'.format(slug, new_ref, subject)
        subprocess.run(['git', '-C', pyclass_repo, 'commit', '-m', message], check=True)
        if args.push:
            branch = git(pyclass_repo, 'rev-parse', '--abbrev-ref', 'HEAD')
            subprocess.run(['git', '-C', pyclass_repo, 'push', 'origin', branch], check=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Failure as exc:
        print('error: {}'.format(exc), file=sys.stderr)
        sys.exit(2)
