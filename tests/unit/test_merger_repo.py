#!/usr/bin/env python

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright 2014 Wikimedia Foundation Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import logging
import os

import git
import testtools

from zuul.merger.merger import Repo
from tests.base import ZuulTestCase, FIXTURE_DIR, simple_layout


class TestMergerRepo(ZuulTestCase):

    log = logging.getLogger("zuul.test.merger.repo")
    tenant_config_file = 'config/single-tenant/main.yaml'
    workspace_root = None

    def setUp(self):
        super(TestMergerRepo, self).setUp()
        self.workspace_root = os.path.join(self.test_root, 'workspace')

    def test_ensure_cloned(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')

        # Forge a repo having a submodule
        parent_repo = git.Repo(parent_path)
        parent_repo.git.submodule('add', os.path.join(
            self.upstream_root, 'org/project2'), 'subdir')
        parent_repo.index.commit('Adding project2 as a submodule in subdir')
        # git 1.7.8 changed .git from being a directory to a file pointing
        # to the parent repository /.git/modules/*
        self.assertTrue(os.path.exists(
            os.path.join(parent_path, 'subdir', '.git')),
            msg='.git file in submodule should be a file')

        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0')
        self.assertTrue(
            os.path.isdir(os.path.join(self.workspace_root, 'subdir')),
            msg='Cloned repository has a submodule placeholder directory')
        self.assertFalse(os.path.exists(
            os.path.join(self.workspace_root, 'subdir', '.git')),
            msg='Submodule is not initialized')

        sub_repo = Repo(
            os.path.join(self.upstream_root, 'org/project2'),
            os.path.join(self.workspace_root, 'subdir'),
            'none@example.org', 'User Name', '0', '0')
        self.assertTrue(os.path.exists(
            os.path.join(self.workspace_root, 'subdir', '.git')),
            msg='Cloned over the submodule placeholder')

        self.assertEqual(
            os.path.join(self.upstream_root, 'org/project1'),
            work_repo.createRepoObject().remotes[0].url,
            message="Parent clone still point to upstream project1")

        self.assertEqual(
            os.path.join(self.upstream_root, 'org/project2'),
            sub_repo.createRepoObject().remotes[0].url,
            message="Sub repository points to upstream project2")

    def test_clone_timeout(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        self.patch(git.Git, 'GIT_PYTHON_GIT_EXECUTABLE',
                   os.path.join(FIXTURE_DIR, 'fake_git.sh'))
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0',
                         git_timeout=0.001, retry_attempts=1)
        # TODO: have the merger and repo classes catch fewer
        # exceptions, including this one on initialization.  For the
        # test, we try cloning again.
        with testtools.ExpectedException(git.exc.GitCommandError,
                                         '.*exit code\(-9\)'):
            work_repo._ensure_cloned()

    def test_fetch_timeout(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0',
                         retry_attempts=1)
        work_repo.git_timeout = 0.001
        self.patch(git.Git, 'GIT_PYTHON_GIT_EXECUTABLE',
                   os.path.join(FIXTURE_DIR, 'fake_git.sh'))
        with testtools.ExpectedException(git.exc.GitCommandError,
                                         '.*exit code\(-9\)'):
            work_repo.update()

    def test_fetch_retry(self):
        parent_path = os.path.join(self.upstream_root, 'org/project1')
        work_repo = Repo(parent_path, self.workspace_root,
                         'none@example.org', 'User Name', '0', '0',
                         retry_interval=1)
        self.patch(git.Git, 'GIT_PYTHON_GIT_EXECUTABLE',
                   os.path.join(FIXTURE_DIR, 'git_fetch_error.sh'))
        work_repo.update()
        # This is created on the first fetch
        self.assertTrue(os.path.exists(os.path.join(
            self.workspace_root, 'stamp1')))
        # This is created on the second fetch
        self.assertTrue(os.path.exists(os.path.join(
            self.workspace_root, 'stamp2')))


class TestMergerWithAuthUrl(ZuulTestCase):
    config_file = 'zuul-github-driver.conf'

    git_url_with_auth = True

    @simple_layout('layouts/merging-github.yaml', driver='github')
    def test_changing_url(self):
        """
        This test checks that if getGitUrl returns different urls for the same
        repo (which happens if an access token is part of the url) then the
        remote urls are changed in the merger accordingly. This tests directly
        the merger.
        """

        merger = self.executor_server.merger
        repo = merger.getRepo('github', 'org/project')
        first_url = repo.remote_url

        repo = merger.getRepo('github', 'org/project')
        second_url = repo.remote_url

        # the urls should differ
        self.assertNotEqual(first_url, second_url)

    @simple_layout('layouts/merging-github.yaml', driver='github')
    def test_changing_url_end_to_end(self):
        """
        This test checks that if getGitUrl returns different urls for the same
        repo (which happens if an access token is part of the url) then the
        remote urls are changed in the merger accordingly. This is an end to
        end test.
        """

        A = self.fake_github.openFakePullRequest('org/project', 'master',
                                                 'PR title')
        self.fake_github.emitEvent(A.getCommentAddedEvent('merge me'))
        self.waitUntilSettled()
        self.assertTrue(A.is_merged)

        # get remote url of org/project in merger
        repo = self.executor_server.merger.repos.get('github.com/org/project')
        self.assertIsNotNone(repo)
        git_repo = git.Repo(repo.local_path)
        first_url = list(git_repo.remotes[0].urls)[0]

        B = self.fake_github.openFakePullRequest('org/project', 'master',
                                                 'PR title')
        self.fake_github.emitEvent(B.getCommentAddedEvent('merge me again'))
        self.waitUntilSettled()
        self.assertTrue(B.is_merged)

        repo = self.executor_server.merger.repos.get('github.com/org/project')
        self.assertIsNotNone(repo)
        git_repo = git.Repo(repo.local_path)
        second_url = list(git_repo.remotes[0].urls)[0]

        # the urls should differ
        self.assertNotEqual(first_url, second_url)
