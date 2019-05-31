#!/usr/bin/env python3
#
# Copyright (C) 2019 Collabora Limited
# Author: Guillaume Tucker <guillaume.tucker@collabora.com>
#
# This module is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2.1 of the License, or (at your option)
# any later version.
#
# This library is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import argparse
import datetime
import glob
import json
import os
import requests
import subprocess
import sys
import urllib

GITHUB_API = "https://api.github.com/"

PROJECTS = {
    'kernelci-core': {
        'url': "https://github.com/kernelci/kernelci-core.git",
        'push-url': "git@github.com:kernelci/kernelci-core.git"
    },
    'kernelci-backend': {
        'url': "https://github.com/kernelci/kernelci-backend.git",
        'push-url': "git@github.com:kernelci/kernelci-backend.git"
    },
    'kernelci-frontend': {
        'url': "https://github.com/kernelci/kernelci-frontend.git",
        'push-url': "git@github.com:kernelci/kernelci-frontend.git"
    },
}


def shell_cmd(cmd):
    subprocess.check_output(cmd, shell=True)


def ssh_agent(ssh_key, cmd):
    if ssh_key:
        cmd = "ssh-agent sh -c 'ssh-add {key}; {cmd}'".format(
            key=ssh_key, cmd=cmd)
    shell_cmd(cmd)


def checkout_repository(args, path, project):
    if not os.path.exists(path):
        shell_cmd("""\
git clone {url} {path}
cd {path}
git remote set-url --push origin {push}
""".format(path=path, url=project['url'], push=project['push-url']))

    shell_cmd("""\
cd {path}
git reset --hard --merge
git fetch origin master
git checkout FETCH_HEAD
""".format(path=path))


def get_pull_requests(args):
    path = '/'.join(['repos', args.namespace, args.project, 'pulls'])
    base_url = urllib.parse.urljoin(GITHUB_API, path)
    url_params = urllib.parse.urlencode({'state': 'open'})
    url = '?'.join([base_url, url_params])
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()
    return data


def pull(args, pr, path):
    head = pr['head']
    branch = head['ref']
    user = head['repo']['owner']['login']
    try:
        shell_cmd("""\
cd {path}
git pull --no-ff --no-edit {origin} {branch}
""".format(path=path, origin=head['repo']['clone_url'], branch=branch))
    except subprocess.CalledProcessError:
        print("WARNING: Failed to pull branch {} from {}".format(branch, user))
        shell_cmd("""\
cd {path}
git reset --merge
""".format(path=path))
        return False
    return True


def apply_patches(args, path, patches_path):
    patches = sorted(glob.glob(os.path.join(patches_path, '*.patch')))
    for patch in patches:
        print("Applying patch: {}".format(patch))
        try:
            shell_cmd("""\
cat {patch} | (cd {path} && git am)
""".format(path=path, patch=patch))
        except subprocess.CalledProcessError:
            print("WARNING: Failed to apply patch")
            shell_cmd("""\
cd {path}
git am --abort
""".format(path=path))
            return False
    return True


def create_tag(args, path):
    tag = args.tag or "staging-{}".format(
        datetime.date.today().strftime('%Y%m%d'))
    print("Tag: {}".format(tag))
    shell_cmd("""\
cd {path}
git tag -l | grep {tag} && git tag -d {tag}
git tag -a {tag} -m {tag}
""".format(path=path, tag=tag))
    return tag


def push_tag_and_branch(args, path, tag):
    ssh_agent(args.ssh_key, """\
cd {path}
git push --force origin HEAD:{branch} {tag}
""".format(path=path, branch=args.branch, tag=tag))


def main(args):
    path = os.path.join('checkout', args.project)
    project = PROJECTS.get(args.project)
    checkout_repository(args, path, project)
    prs = get_pull_requests(args)
    skip = []
    for user_branch in args.skip:
        user, _, branch = user_branch.partition('/')
        skip.append((user, branch))
    for pr in prs:
        head = pr['head']
        branch = head['ref']
        user = head['repo']['owner']['login']
        if (user, branch) in skip:
            print("Skipping branch {} from {}".format(branch, user))
        else:
            pull(args, pr, path)
    patches_path = os.path.join('patches', args.project)
    if not apply_patches(args, path, patches_path):
        print("Aborting, all patches must apply.")
        return False
    tag = create_tag(args, path)
    if args.push:
        push_tag_and_branch(args, path, tag)


if __name__ == '__main__':
    parser = argparse.ArgumentParser("Create staging.kernelci.org branches")
    parser.add_argument("project", choices=PROJECTS.keys(),
                        help="Name of the Github project")
    parser.add_argument("--path",
                        help="Path to the local checkout, default is $PWD")
    parser.add_argument("--tag",
                        help="Tag to create, default is to use current date")
    parser.add_argument("--branch", default="staging.kernelci.org",
                        help="Name of the branch to force-push to")
    parser.add_argument("--namespace", default='kernelci',
                        help="Github project namespace")
    parser.add_argument("--skip", nargs='+', default=[],
                        help="Name of user/branch pairs to skip")
    parser.add_argument("--ssh-key",
                        help="Path to SSH key to push branches and tags")
    parser.add_argument("--push", action="store_true",
                        help="Push the resulting branch and tag")
    args = parser.parse_args(sys.argv[1:])
    main(args)
