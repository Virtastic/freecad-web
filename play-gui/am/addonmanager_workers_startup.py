# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2019 Yorik van Havre <yorik@uncreated.net>
# SPDX-FileCopyrightText: 2022 FreeCAD Project Association
# SPDX-FileNotice: Part of the AddonManager.

################################################################################
#                                                                              #
#   This addon is free software: you can redistribute it and/or modify         #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   This addon is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with this addon. If not, see https://www.gnu.org/licenses    #
#                                                                              #
################################################################################

"""Worker thread classes for Addon Manager startup"""
import hashlib
import io
import json
import os
from typing import List
import xml.etree.ElementTree
import zipfile

from PySideWrapper import QtCore
from addonmanager_installation_manifest import InstallationManifest

from addonmanager_macro import Macro
from Addon import Addon, MissingDependencies
from AddonCatalog import AddonCatalog
from AddonStats import AddonStats
import NetworkManager
from addonmanager_git import initialize_git, GitFailed
from addonmanager_metadata import MetadataReader, get_branch_from_metadata
import addonmanager_freecad_interface as fci
from addonmanager_fcweb_async import AsyncWorker, defer

translate = fci.translate

# pylint: disable=c-extension-no-member, too-few-public-methods, too-many-instance-attributes


class CreateAddonListWorker(AsyncWorker):
    """This worker updates the list of available workbenches, emitting an "addon_repo"
    signal for each Addon as they are processed."""

    addon_repo = QtCore.Signal(object)
    progress_made = QtCore.Signal(str, int, int)
    old_backups_found = QtCore.Signal(object)

    MAX_ATTEMPTS = 3
    RETRY_DELAY_MS = 3000
    ATTEMPT_TIMEOUT_MS = 30000

    def __init__(self, parent=None):
        AsyncWorker.__init__(self, parent)
        self.setObjectName("CreateAddonListWorker")

        self.package_names = []
        self.mod_dir = fci.DataPaths().mod_dir
        # Upstream set this to QThread.currentThread() inside run(). There is no worker
        # thread now, and AsyncWorker carries the same isInterruptionRequested(), so the
        # upstream interruption checks below work unchanged by pointing it at self.
        self.current_thread = self

    def run(self):
        """Populates the list of addons, without blocking.

        Upstream ran straight-line: custom addons, then get_cache("addon_catalog"), then
        get_cache("macro"), each of those doing blocking HTTP. Blocking is fatal here -- the
        Qt event loop is what delivers the reply, so waiting for one inside a slot starves
        it (measured: the app froze and never opened). The same four fetches now run as a
        state machine driven by completion callbacks:

            CUSTOM -> hash(catalog) -> [zip(catalog)] -> process -> hash(macro)
                   -> [zip(macro)] -> process -> finished

        Every non-network step below is upstream's code, unchanged.
        """
        try:
            self._get_custom_addons()
        except (ConnectionError, RuntimeError, OSError) as e:
            fci.Console.PrintError("Failed to load custom addons: %s\n" % e)
        self.progress_made.emit("Custom addons loaded", 5, 100)
        self._begin_cache("addon_catalog", self._addon_cache_ready)

    # -- the two-step cache sub-machine, replacing get_cache/new_cache_available -------
    def _begin_cache(self, name, on_ready):
        """Step A: fetch <url>.sha256 and decide whether the local copy is stale."""
        self._cache_name = name
        self._on_ready = on_ready
        self._cache_path = os.path.join(
            fci.DataPaths().cache_dir, "AddonManager", name + "_cache.json"
        )
        self._have_local = os.path.isfile(self._cache_path)
        url = fci.Preferences().get(f"{name}_cache_url")
        self._get(
            url + ".sha256",
            self._hash_arrived,
            timeout_ms=self.ATTEMPT_TIMEOUT_MS,
            attempts=self.MAX_ATTEMPTS,
            retry_delay_ms=self.RETRY_DELAY_MS,
        )

    def _hash_arrived(self, ok, data):
        if ok:
            sha = data.decode("utf8", "replace").strip()
            stale = sha != fci.Preferences().get(
                f"last_fetched_{self._cache_name}_cache_hash"
            )
        else:
            # Could not check. Upstream fell back to the local copy in this case; only go
            # to the network if there is nothing on disk at all.
            stale = not self._have_local
        if not stale and self._have_local:
            self._on_ready(self.get_local_cache(self._cache_path))
            return
        self._get(
            fci.Preferences().get(f"{self._cache_name}_cache_url"),
            self._zip_arrived,
            timeout_ms=self.ATTEMPT_TIMEOUT_MS,
            attempts=self.MAX_ATTEMPTS,
            retry_delay_ms=self.RETRY_DELAY_MS,
        )

    def _zip_arrived(self, ok, data):
        """Step B. Everything past the fetch is upstream get_remote_cache()."""
        text = ""
        if ok:
            try:
                text = self._unpack_cache_zip(data)
            except (RuntimeError, FileNotFoundError, zipfile.BadZipFile, OSError) as e:
                fci.Console.PrintError(
                    "Failed to unpack %s cache: %s\n" % (self._cache_name, e)
                )
        if not text and self._have_local:
            fci.Console.PrintWarning(
                "Using local %s cache: %s\n" % (self._cache_name, self._cache_path)
            )
            text = self.get_local_cache(self._cache_path)
        self._on_ready(text)

    def _unpack_cache_zip(self, zip_data):
        sha256 = hashlib.sha256(zip_data).hexdigest()
        fci.Preferences().set(f"last_fetched_{self._cache_name}_cache_hash", sha256)
        name = f"{self._cache_name}_cache.json"
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_file:
            if name not in zip_file.namelist():
                raise FileNotFoundError(f"{name} not found in ZIP")
            with zip_file.open(name) as target_file:
                blob = target_file.read()
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
        with open(self._cache_path, "wb") as f:
            f.write(blob)
        return blob.decode("utf-8")

    def _addon_cache_ready(self, text):
        if text:
            self.process_addon_cache(text)
        self.progress_made.emit("Addon catalog loaded", 20, 100)
        self._begin_cache("macro", self._macro_cache_ready)

    def _macro_cache_ready(self, text):
        if text:
            self.process_macro_cache(text)
        self.progress_made.emit("Macros loaded", 100, 100)
        self._finish()

    def _get_custom_addons(self):

        # querying custom addons first
        addon_list = fci.Preferences().get("CustomRepositories").split("\n")
        custom_addons = []
        for addon in addon_list:
            if " " in addon:
                addon_and_branch = addon.split(" ")
                custom_addons.append({"url": addon_and_branch[0], "branch": addon_and_branch[1]})
            else:
                custom_addons.append({"url": addon, "branch": "master"})
        for addon in custom_addons:
            if self.current_thread.isInterruptionRequested():
                return
            if addon and addon["url"]:
                if addon["url"][-1] == "/":
                    addon["url"] = addon["url"][0:-1]  # Strip trailing slash
                addon["url"] = addon["url"].split(".git")[0]  # Remove .git
                name: str = addon["url"].split("/")[-1]
                if name in self.package_names:
                    # We already have something with this name, skip this one
                    fci.Console.PrintWarning(
                        translate("AddonsInstaller", "WARNING: Duplicate addon {} ignored").format(
                            name
                        )
                    )
                    continue
                fci.Console.PrintLog(
                    f"Adding custom location {addon['url']} with branch {addon['branch']}\n"
                )
                self.package_names.append(name)
                addon_dir = os.path.join(self.mod_dir, name)
                if os.path.exists(addon_dir) and os.listdir(addon_dir):
                    state = Addon.Status.UNCHECKED
                else:
                    state = Addon.Status.NOT_INSTALLED
                repo = Addon(name, addon["url"], state, addon["branch"])
                md_file = os.path.join(addon_dir, "package.xml")
                if os.path.isfile(md_file):
                    try:
                        repo.installed_metadata = MetadataReader.from_file(md_file)
                        repo.installed_version = repo.installed_metadata.version
                        repo.updated_timestamp = os.path.getmtime(md_file)
                        repo.verify_url_and_branch(addon["url"], addon["branch"])
                    except xml.etree.ElementTree.ParseError:
                        fci.Console.PrintWarning(
                            f"An invalid or corrupted package.xml file was installed for custom addon {name}... ignoring the bad data.\n"
                        )

                self.addon_repo.emit(repo)

    def get_cache(self, cache_name: str) -> str:
        cache_file_name = cache_name + "_cache.json"
        full_path = os.path.join(fci.DataPaths().cache_dir, "AddonManager", cache_file_name)
        have_local_cache = os.path.isfile(full_path)
        remote_update_available = CreateAddonListWorker.new_cache_available(cache_name)
        if remote_update_available or not have_local_cache:
            try:
                return self.get_remote_cache(cache_name)
            except (RuntimeError, FileNotFoundError, ConnectionError) as e:
                if have_local_cache:
                    fci.Console.PrintWarning(
                        f"Failed to load remote cache, using local cache instead: {full_path}"
                    )
                    return self.get_local_cache(full_path)
                else:
                    fci.Console.PrintError(f"Failed to load remote cache: {str(e)}\n")
                    return ""
        else:
            return self.get_local_cache(full_path)

    @classmethod
    def get_remote_cache(cls, cache_name: str) -> str:
        # Unreachable in this build. blocking_get_with_retries spins
        # QCoreApplication.processEvents() until the reply lands, but on wasm the
        # browser drives that loop, so the spin starves the very reply it waits for.
        # Use _begin_cache instead.
        raise RuntimeError(
            "get_remote_cache blocks and cannot be used in the browser build; "
            "use CreateAddonListWorker._begin_cache"
        )
        url = fci.Preferences().get(f"{cache_name}_cache_url")
        p = NetworkManager.AM_NETWORK_MANAGER.blocking_get_with_retries(
            url, cls.ATTEMPT_TIMEOUT_MS, cls.MAX_ATTEMPTS, cls.RETRY_DELAY_MS
        )
        if QtCore.QThread.currentThread().isInterruptionRequested():
            return ""
        if not p:
            raise RuntimeError(
                f"Failed to download cache from {url} after {cls.MAX_ATTEMPTS} attempts"
            )
        zip_data = p.data()
        sha256 = hashlib.sha256(zip_data).hexdigest()
        fci.Preferences().set(f"last_fetched_{cache_name}_cache_hash", sha256)

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_file:
            if f"{cache_name}_cache.json" in zip_file.namelist():
                with zip_file.open(f"{cache_name}_cache.json") as target_file:
                    cache_text_data = target_file.read()
                cached_file = os.path.join(
                    fci.DataPaths().cache_dir, "AddonManager", f"{cache_name}_cache.json"
                )
                os.makedirs(os.path.dirname(cached_file), exist_ok=True)
                with open(cached_file, "wb") as f:
                    f.write(cache_text_data)
            else:
                raise FileNotFoundError(f"{cache_name}_cache.json not found in ZIP")
        return cache_text_data.decode("utf-8")

    @staticmethod
    def get_local_cache(cache_file: str) -> str:
        try:
            with open(cache_file, encoding="utf-8") as f:
                return f.read()
        except RuntimeError as e:
            fci.Console.PrintError(
                f"The Addon Manager failed to load the cached addon catalog from {cache_file}.\n"
            )
            fci.Console.PrintError(str(e) + "\n")
            return ""

    @classmethod
    def new_cache_available(cls, cache_name: str) -> bool:
        # Unreachable in this build -- see get_remote_cache. _hash_arrived does this
        # comparison from a completion callback instead.
        raise RuntimeError(
            "new_cache_available blocks and cannot be used in the browser build"
        )
        """Downloads and checks the hash of the remote catalog and compares it to our last-fetched hash"""
        hash_url = fci.Preferences().get(f"{cache_name}_cache_url") + ".sha256"
        p = NetworkManager.AM_NETWORK_MANAGER.blocking_get_with_retries(
            hash_url, cls.ATTEMPT_TIMEOUT_MS, cls.MAX_ATTEMPTS, cls.RETRY_DELAY_MS
        )
        if QtCore.QThread.currentThread().isInterruptionRequested():
            return False
        if not p:
            raise RuntimeError(
                f"Failed to download cache hash from remote server {hash_url} after {cls.MAX_ATTEMPTS} attempts"
            )
        sha256 = p.data().decode("utf8")
        if sha256 != fci.Preferences().get(f"last_fetched_{cache_name}_cache_hash"):
            return True
        return False

    def process_addon_cache(self, catalog_text_data):
        catalog = AddonCatalog(json.loads(catalog_text_data))
        manifest = InstallationManifest(catalog)
        for addon_id in catalog.get_available_addon_ids():
            if addon_id in self.package_names:
                # We already have something with this name, skip this one
                fci.Console.PrintWarning(
                    translate(
                        "AddonsInstaller",
                        "WARNING: Custom addon '{}' is overriding the one in the official addon catalog\n",
                    ).format(addon_id)
                )
                continue
            self.package_names.append(addon_id)
            branches = catalog.get_available_branches(addon_id)
            if not branches:
                fci.Console.PrintWarning(
                    f"Failed to find any compatible branches for '{addon_id}'. This is an internal error, please report it to the developers.\n"
                )
                continue

            installed_branch_name = None
            if manifest.contains(addon_id):
                # Then this addon is currently installed: make sure we use the correct branch
                installed_branch_name = manifest.get_addon_info(addon_id)["branch_display_name"]
                fci.Console.PrintLog(
                    f"Found installed addon '{addon_id}' with branch '{installed_branch_name}'\n"
                )
            addon_instances = {}
            name_of_first_entry = None
            for branch_display_name in branches:
                try:
                    addon = catalog.get_addon_from_id(addon_id, branch_display_name)
                    addon_instances[branch_display_name] = addon
                    if name_of_first_entry is None:
                        name_of_first_entry = branch_display_name
                    else:
                        fci.Console.PrintMessage(
                            f"Found additional branch '{branch_display_name}' for addon {addon_id}\n"
                        )
                except Exception as e:
                    # Any exception that occurs gets absorbed here in an attempt to find a working
                    # branch. Only if all proposed branches fail does this become an error that
                    # causes us to skip the addon
                    fci.Console.PrintWarning(
                        f"Could not load branch '{branch_display_name}' for addon {addon_id}: {str(e)}\n"
                    )
                    continue
            if name_of_first_entry is None:
                fci.Console.PrintError(
                    f"Failed to load the addon {addon_id} from the addon catalog, skipping it.\n"
                )
                continue
            primary_branch_name = (
                installed_branch_name if installed_branch_name in branches else name_of_first_entry
            )
            for branch_display_name in branches:
                if branch_display_name != primary_branch_name:
                    # Only add non-primary addons to the sub_addons list so that the primary addon
                    # doesn't list *itself* as a sub-addon
                    addon_instances[primary_branch_name].sub_addons[branch_display_name] = (
                        addon_instances[branch_display_name]
                    )
            self.addon_repo.emit(addon_instances[primary_branch_name])

        if manifest.old_backups:
            self.old_backups_found.emit(manifest.old_backups)

    def process_macro_cache(self, catalog_text_data):
        cache_object: dict = json.loads(catalog_text_data)
        for macro_name, cache_data in cache_object.items():
            macro = Macro.from_cache(cache_data)
            addon = Addon.from_macro(macro)
            self.addon_repo.emit(addon)


class CheckSingleUpdateWorker(QtCore.QObject):
    """This worker is a little different from the others: the actual recommended way of
    running in a QThread is to make a worker object that gets moved into the thread."""

    update_status = QtCore.Signal(int)

    def __init__(self, repo: Addon, parent: QtCore.QObject = None):
        super().__init__(parent)
        self.repo = repo

    def do_work(self):
        """Use the UpdateChecker class to do the work of this function, depending on the
        type of Addon"""

        checker = UpdateChecker()
        if self.repo.repo_type == Addon.Kind.WORKBENCH:
            checker.check_workbench(self.repo)
        elif self.repo.repo_type == Addon.Kind.MACRO:
            checker.check_macro(self.repo)
        elif self.repo.repo_type == Addon.Kind.PACKAGE:
            checker.check_package(self.repo)

        self.update_status.emit(self.repo.update_status)


class CheckWorkbenchesForUpdatesWorker(AsyncWorker):
    """This worker checks for available updates for all workbenches"""

    update_status = QtCore.Signal(Addon)
    progress_made = QtCore.Signal(str, int, int)

    def __init__(self, repos: List[Addon], parent=None):

        AsyncWorker.__init__(self, parent)
        self.setObjectName("CheckWorkbenchesForUpdatesWorker")
        self.repos = repos
        # Upstream set this to QThread.currentThread() inside run(). There is no worker
        # thread now, and AsyncWorker carries the same isInterruptionRequested(), so the
        # upstream interruption checks below work unchanged by pointing it at self.
        self.current_thread = self
        self.mod_dir = fci.DataPaths().mod_dir

    def run(self):
        """One repo per event-loop turn.

        The work itself is disk-only here -- there is no git binary in this build, so
        check_workbench sets CANNOT_CHECK and returns immediately -- but the loop can run
        to ~175 addons, and doing that in one synchronous burst freezes the tab and leaves
        the progress bar nowhere to paint. singleShot(0) between repos yields to the event
        loop, which is also what lets requestInterruption() take effect mid-scan.
        """
        self._checker = UpdateChecker()
        self._queue = list(self.repos)
        self._count = 0
        self._next_repo()

    def _next_repo(self):
        if self._interrupted or not self._queue:
            self._finish()
            return
        repo = self._queue.pop(0)
        self._count += 1
        self.progress_made.emit(
            translate("AddonsInstaller", "Checking {} for update").format(repo.display_name),
            self._count,
            len(self.repos),
        )
        if repo.status() == Addon.Status.UNCHECKED:
            try:
                if repo.repo_type == Addon.Kind.WORKBENCH:
                    self._checker.check_workbench(repo)
                elif repo.repo_type == Addon.Kind.MACRO:
                    self._checker.check_macro(repo)
                elif repo.repo_type == Addon.Kind.PACKAGE:
                    self._checker.check_package(repo)
            except Exception as e:
                # A single bad addon must not take down the whole update scan.
                fci.Console.PrintWarning(
                    "Update check failed for %s: %r\n" % (repo.display_name, e)
                )
        self.update_status.emit(repo)
        defer(0, self._next_repo, self)


class UpdateChecker:
    """A utility class used by the CheckWorkbenchesForUpdatesWorker class. Each function is
    designed for a specific Addon type and modifies the passed-in Addon with the determined
    update status."""

    def __init__(self):
        self.mod_dir: str = fci.DataPaths().mod_dir
        self.git_manager = initialize_git()

    def override_mod_directory(self, mod_dir):
        """Primarily for use when testing, sets an alternate directory to use for mods"""
        self.mod_dir = mod_dir

    def check_workbench(self, wb):
        """Given a workbench Addon wb, check it for updates using git. If git is not
        available, does nothing."""
        if not self.git_manager:
            wb.set_status(Addon.Status.CANNOT_CHECK)
            return
        clone_dir = os.path.join(self.mod_dir, wb.name)
        if os.path.exists(clone_dir):
            # mark as already installed AND already checked for updates
            if not os.path.exists(os.path.join(clone_dir, ".git")):
                with wb.git_lock:
                    self.git_manager.repair(wb.url, clone_dir)
            with wb.git_lock:
                try:
                    status = self.git_manager.status(clone_dir)
                    if "(no branch)" in status:
                        # By definition, in a detached-head state we cannot
                        # update, so don't even bother checking.
                        wb.set_status(Addon.Status.NO_UPDATE_AVAILABLE)
                        wb.branch = self.git_manager.current_branch(clone_dir)
                        return
                except GitFailed as e:
                    fci.Console.PrintWarning(
                        "AddonManager: "
                        + translate(
                            "AddonsInstaller",
                            "Unable to fetch Git updates for workbench {}",
                        ).format(wb.name)
                        + "\n"
                    )
                    fci.Console.PrintWarning(str(e) + "\n")
                    wb.set_status(Addon.Status.CANNOT_CHECK)
                else:
                    try:
                        if self.git_manager.update_available(clone_dir):
                            wb.set_status(Addon.Status.UPDATE_AVAILABLE)
                        else:
                            wb.set_status(Addon.Status.NO_UPDATE_AVAILABLE)
                    except GitFailed:
                        fci.Console.PrintWarning(
                            translate("AddonsInstaller", "Git status failed for {}").format(wb.name)
                            + "\n"
                        )
                        wb.set_status(Addon.Status.CANNOT_CHECK)

    def _branch_name_changed(self, package: Addon) -> bool:
        clone_dir = os.path.join(self.mod_dir, package.name)
        installed_metadata_file = os.path.join(clone_dir, "package.xml")
        if not os.path.isfile(installed_metadata_file):
            return False
        if not hasattr(package, "metadata") or package.metadata is None:
            return False
        try:
            installed_metadata = MetadataReader.from_file(installed_metadata_file)
            installed_default_branch = get_branch_from_metadata(installed_metadata)
            remote_default_branch = get_branch_from_metadata(package.metadata)
            if installed_default_branch != remote_default_branch:
                return True
        except RuntimeError:
            return False
        return False

    def check_package(self, package: Addon) -> None:
        """Given a packaged Addon package, check it for updates. If git is available, that is
        used. If not, the package's metadata is examined, and if the metadata file has changed
        compared to the installed copy, an update is flagged. In addition, a change to the
        default branch name triggers an update."""

        clone_dir = self.mod_dir + os.sep + package.name
        if os.path.exists(clone_dir):

            # First, see if the branch name changed, which automatically triggers an update
            if self._branch_name_changed(package):
                package.set_status(Addon.Status.UPDATE_AVAILABLE)
                return

            # Next, try to just do a git-based update, which will give the most accurate results:
            if self.git_manager:
                self.check_workbench(package)
                if package.status() != Addon.Status.CANNOT_CHECK:
                    # It worked, exit now
                    return

            # If we were unable to do a git-based update, try using the package.xml file instead:
            installed_metadata_file = os.path.join(clone_dir, "package.xml")
            if not os.path.isfile(installed_metadata_file):
                # If there is no package.xml file, then it's because the package author added it
                # after the last time the local installation was updated. By definition, then,
                # there is an update available, if only to download the new XML file.
                package.set_status(Addon.Status.UPDATE_AVAILABLE)
                package.installed_version = None
                return
            package.updated_timestamp = os.path.getmtime(installed_metadata_file)
            try:
                installed_metadata = MetadataReader.from_file(installed_metadata_file)
                package.installed_version = installed_metadata.version
                # Packages are considered up to date if the metadata version matches.
                # Authors should update their version string when they want the addon
                # manager to alert users of a new version.
                if package.metadata.version != installed_metadata.version:
                    package.set_status(Addon.Status.UPDATE_AVAILABLE)
                else:
                    package.set_status(Addon.Status.NO_UPDATE_AVAILABLE)
            except RuntimeError:
                fci.Console.PrintWarning(
                    translate(
                        "AddonsInstaller",
                        "Failed to read metadata from {name}",
                    ).format(name=installed_metadata_file)
                    + "\n"
                )
                package.set_status(Addon.Status.CANNOT_CHECK)

    @staticmethod
    def check_macro(macro_wrapper: Addon) -> None:
        """Check to see if the online copy of the macro's code differs from the local copy."""

        # Make sure this macro has its code downloaded:
        try:
            if not macro_wrapper.macro.parsed and macro_wrapper.macro.on_git:
                macro_wrapper.macro.fill_details_from_file(macro_wrapper.macro.src_filename)
            elif not macro_wrapper.macro.parsed and macro_wrapper.macro.on_wiki:
                mac = macro_wrapper.macro.name.replace(" ", "_")
                mac = mac.replace("&", "%26")
                mac = mac.replace("+", "%2B")
                url = "https://wiki.freecad.org/Macro_" + mac
                macro_wrapper.macro.fill_details_from_wiki(url)
        except RuntimeError:
            fci.Console.PrintWarning(
                translate(
                    "AddonsInstaller",
                    "Failed to fetch code for macro '{name}'",
                ).format(name=macro_wrapper.macro.name)
                + "\n"
            )
            macro_wrapper.set_status(Addon.Status.CANNOT_CHECK)
            return

        try:
            hasher1 = hashlib.sha1(usedforsecurity=False)
            hasher2 = hashlib.sha1(usedforsecurity=False)
        except TypeError:
            # To continue to support Python 3.8, we need to fall back if the usedforsecurity
            # is not available. This code should be removed when we drop support for 3.8.
            hasher1 = hashlib.sha1()
            hasher2 = hashlib.sha1()
        hasher1.update(macro_wrapper.macro.code.encode("utf-8"))
        new_sha1 = hasher1.hexdigest()
        test_file_one = os.path.join(fci.DataPaths().macro_dir, macro_wrapper.macro.filename)
        test_file_two = os.path.join(
            fci.DataPaths().macro_dir, "Macro_" + macro_wrapper.macro.filename
        )
        if os.path.exists(test_file_one):
            with open(test_file_one, "rb") as f:
                contents = f.read()
                hasher2.update(contents)
                old_sha1 = hasher2.hexdigest()
        elif os.path.exists(test_file_two):
            with open(test_file_two, "rb") as f:
                contents = f.read()
                hasher2.update(contents)
                old_sha1 = hasher2.hexdigest()
        else:
            return
        if new_sha1 == old_sha1:
            macro_wrapper.set_status(Addon.Status.NO_UPDATE_AVAILABLE)
        else:
            macro_wrapper.set_status(Addon.Status.UPDATE_AVAILABLE)


class GetBasicAddonStatsWorker(AsyncWorker):
    """Fetch data from an addon stats repository."""

    update_addon_stats = QtCore.Signal(Addon)

    MAX_ATTEMPTS = 3
    RETRY_DELAY_MS = 3000
    ATTEMPT_TIMEOUT_MS = 30000

    def __init__(self, url: str, addons: List[Addon], parent: QtCore.QObject = None):
        super().__init__(parent)
        self.setObjectName("GetBasicAddonStatsWorker")
        self.url = url
        self.addons = addons

    def run(self):
        """Fetch the remote data and load it into the addons (non-blocking)."""
        self._get(
            self.url,
            self._stats_arrived,
            timeout_ms=self.ATTEMPT_TIMEOUT_MS,
            attempts=self.MAX_ATTEMPTS,
            retry_delay_ms=self.RETRY_DELAY_MS,
        )

    def _stats_arrived(self, ok, data):
        if not ok:
            fci.Console.PrintError(
                translate(
                    "AddonsInstaller",
                    "Failed to get addon statistics from {} -- only sorting alphabetically will"
                    " be accurate\n",
                ).format(self.url)
            )
            self._finish()
            return
        try:
            json_result = json.loads(data.decode("utf8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            fci.Console.PrintError("%s: %s\n" % (self.url, e))
            self._finish()
            return

        for addon in self.addons:
            if addon.url in json_result:
                addon.stats = AddonStats.from_json(json_result[addon.url])
                self.update_addon_stats.emit(addon)
        self._finish()


class GetAddonScoreWorker(AsyncWorker):
    """Fetch data from an addon score file."""

    update_addon_score = QtCore.Signal(Addon)

    MAX_ATTEMPTS = 3
    RETRY_DELAY_MS = 3000
    ATTEMPT_TIMEOUT_MS = 30000

    def __init__(self, url: str, addons: List[Addon], parent: QtCore.QObject = None):
        super().__init__(parent)
        self.setObjectName("GetAddonScoreWorker")
        self.url = url
        self.addons = addons

    def run(self):
        """Fetch the remote data and load it into the addons (non-blocking).

        The TEST branch is synthetic and stays synchronous; only the real fetch moved to a
        callback. _apply_scores holds everything that used to follow the fetch.
        """
        if self.url != "TEST":
            self._get(
                self.url,
                self._score_arrived,
                timeout_ms=self.ATTEMPT_TIMEOUT_MS,
                attempts=self.MAX_ATTEMPTS,
                retry_delay_ms=self.RETRY_DELAY_MS,
            )
            return
        fci.Console.PrintWarning("Running score generation in TEST mode...\n")
        json_result = {}
        for addon in self.addons:
            if addon.macro:
                json_result[addon.name] = len(addon.macro.comment) if addon.macro.comment else 0
            else:
                json_result[addon.url] = len(addon.description) if addon.description else 0
        self._apply_scores(json_result)

    def _score_arrived(self, ok, data):
        json_result = {}
        if not ok:
            fci.Console.PrintError(
                translate(
                    "AddonsInstaller",
                    "Failed to get addon score from '{}' -- sorting by score will fail\n",
                ).format(self.url)
            )
            self._finish()
            return
        if True:
            try:
                text_result = data.decode("utf8")
                json_result = json.loads(text_result)
            except UnicodeDecodeError:
                fci.Console.PrintError(
                    translate(
                        "AddonsInstaller",
                        "Failed to decode addon score from '{}' -- sorting by score will fail\n",
                    ).format(self.url)
                )
            except json.JSONDecodeError:
                fci.Console.PrintError(
                    translate(
                        "AddonsInstaller",
                        "Failed to parse addon score from '{}' -- sorting by score will fail\n",
                    ).format(self.url)
                )
            except RuntimeError:
                fci.Console.PrintError(
                    translate(
                        "AddonsInstaller",
                        "Failed to read addon score from '{}' -- sorting by score will fail\n",
                    ).format(self.url)
                )
        self._apply_scores(json_result)

    def _apply_scores(self, json_result):
        for addon in self.addons:
            score = None
            if addon.url in json_result:
                score = json_result[addon.url]
            elif addon.name in json_result:
                score = json_result[addon.name]
            if score is not None:
                try:
                    addon.score = int(score)
                    self.update_addon_score.emit(addon)
                except (ValueError, OverflowError):
                    fci.Console.PrintLog(
                        f"Failed to convert score value '{score}' to an integer for {addon.name}"
                    )
        self._finish()


class CheckForMissingDependenciesWorker(AsyncWorker):
    """A worker class to examine installed addons and check for missing dependencies"""

    progress = QtCore.Signal(str, int, int)

    def __init__(self, addons: List[Addon], parent: QtCore.QObject = None):
        super().__init__(parent)
        self.addons = addons
        self.missing_dependencies = MissingDependencies()

    def run(self):
        self.progress.emit(
            translate("AddonsInstaller", "Checking for missing dependencies"),
            0,
            len(self.addons),
        )

        installed_addons = [
            addon for addon in self.addons if addon.status() != Addon.Status.NOT_INSTALLED
        ]
        counter = 0
        details = ""
        for addon in installed_addons:
            counter += 1
            self.progress.emit(
                translate("AddonsInstaller", "Checking for missing dependencies"),
                counter,
                len(installed_addons),
            )
            if addon.status() != Addon.Status.NOT_INSTALLED:
                deps = MissingDependencies()
                deps.import_from_addon(addon, self.addons)
                if deps.wbs:
                    details += (
                        f"{addon.display_name} is missing workbenches {', '.join(deps.wbs)}\n"
                    )
                if deps.external_addons:
                    details += f"{addon.display_name} is missing addons {', '.join(deps.external_addons)}\n"
                if deps.python_requires:
                    details += f"{addon.display_name} is missing python packages {', '.join(deps.python_requires)}\n"
                self.missing_dependencies.join(deps)

        md = self.missing_dependencies
        message = "\nAddon Missing Dependency Analysis\n"
        message += "---------------------------------\n"
        message += f"Missing FreeCAD Workbenches: {len(md.wbs)}\n"
        message += f"Missing addons: {len(md.external_addons)}\n"
        message += f"Missing required Python packages: {len(md.python_requires)}\n"
        message += f"Missing optional Python packages: {len(md.python_optional)}\n"
        message += f"Minimum required Python version evaluated to {md.python_min_version}\n\n"
        fci.Console.PrintMessage(message)
        fci.Console.PrintLog(details)
        self._finish()
