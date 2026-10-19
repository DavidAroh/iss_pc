# SPDX-License-Identifier: GPL-2.0-or-later
"""The QObject behind the Updates screen. One HTTPS GET to the GitHub releases API when the player
clicks "Check for updates" (or opens the launcher with the option on, off by default); it sends no
data of the player. "Release page" opens the release in the browser. In a packaged build, "Download
and install" fetches the package (updater.py) after a confirmation, checks it, asks again before
installing it into a new folder next to this one, then offers to restart into it."""
import datetime
from pathlib import Path
import sys
import threading

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import releases, report, updater
from .logic import tlg_run


class Updates(QObject):
    changed = Signal()
    fetched = Signal(object)
    dialogChanged = Signal()
    progressed = Signal(object)    # (done, total) from the download thread
    stepDone = Signal(object)      # ('downloaded' | 'installed', value) or an UpdateError

    def __init__(self, backend, probes=None):
        """probes (tests, screenshots): 'fetch' -> f(version) returning the release dict or raising
        UpdateError, 'version' -> the installed version, 'open_url' -> f(url), 'save' -> f(settings),
        'frozen' -> bool, 'port_dir' -> the install folder, 'data_dir' -> the data folder,
        'exe' -> the launcher's file name, 'opener' -> urlopen-like f(request, timeout),
        'launch' -> f(folder), 'quit' -> f()."""
        super().__init__(backend)
        self.backend = backend
        self.probes = probes or {}
        self._checking = False
        self._error = ''
        self._phase = ''          # '' | download | install | ready
        self._progress = (0, 0)
        self._verified = False
        self._archive = None      # the downloaded, checked package
        self._new_dir = None      # the folder it was installed into
        self._cancel = threading.Event()
        self._dialog, self._handlers = {}, {}
        seen = backend.settings.get('update_seen')
        self.release = dict(seen) if isinstance(seen, dict) and seen.get('tag') else None
        self.fetched.connect(self._on_fetched)
        self.progressed.connect(self._on_progress)
        self.stepDone.connect(self._on_step)

    def t(self, key, **fmt):
        return self.backend.t_(key, **fmt)

    # -- state ---------------------------------------------------------------------------------------
    def installed(self):
        if 'version' in self.probes:
            return self.probes['version']()
        return report.current_version((tlg_run.PORT_DIR, tlg_run.REPO_DIR), tlg_run.LOG_DIR)

    def status(self):
        if not self.release:
            return 'none'
        return releases.compare(self.installed(), self.release.get('tag', ''))

    @Property(bool, notify=changed)
    def available(self):
        """A newer version is known (the dot on the rail)."""
        return bool(self.release) and self.status() in ('newer', 'different')

    @Property(str, notify=changed)
    def current(self):
        return self.installed() or self.t('rep_unknown')

    @Property(str, notify=changed)
    def latest(self):
        return self.release['tag'] if self.release else '—'

    @Property(str, notify=changed)
    def published(self):
        return (self.release or {}).get('published', '')

    @Property(bool, notify=changed)
    def checking(self):
        return self._checking

    @Property(bool, notify=changed)
    def canDownload(self):
        return True     # without a known release it opens the releases page

    @Property(str, notify=changed)
    def statusText(self):
        if self._checking:
            return self.t('upd_checking')
        if self._phase == 'ready':
            return self.t('upd_installed', folder=str(self._new_dir))
        if self._error:
            return self._error
        status = self.status()
        tag = self.latest
        if status == 'none':
            return self.t('upd_never')
        return self.t('upd_' + status, tag=tag, current=self.installed())

    @Property(str, notify=changed)
    def tone(self):
        if self._error:
            return 'bad'
        if self._phase == 'ready':
            return 'good'
        return {'newer': 'warn', 'different': 'warn', 'same': 'good'}.get(self.status(), 'info') \
            if not self._checking else 'info'

    @Property(str, notify=changed)
    def notes(self):
        if not self.release:
            return ''
        notes = releases.extract_notes(self.release.get('body', ''), self.backend.t_.pt())
        return notes or self.t('upd_no_notes')

    @Property(bool, notify=changed)
    def checkOnOpen(self):
        return bool(self.backend.settings.get('check_updates_on_open', False))

    @Slot(bool)
    def setCheckOnOpen(self, value):
        self.backend.settings['check_updates_on_open'] = bool(value)
        self._save()
        self.changed.emit()

    def _save(self):
        if 'save' in self.probes:
            self.probes['save'](self.backend.settings)
        else:
            tlg_run.save_settings(self.backend.settings)

    # -- the check -----------------------------------------------------------------------------------
    @Slot()
    def check(self):
        if self._checking:
            return
        self._checking, self._error = True, ''
        self.changed.emit()
        version = self.installed()

        def work():
            fetch = self.probes.get('fetch') or (lambda v: releases.fetch_latest(v))
            try:
                self.fetched.emit(fetch(version))
            except releases.UpdateError as error:
                self.fetched.emit(error)
            except Exception as error:    # never let a surprise leave the screen stuck on "checking"
                self.fetched.emit(releases.UpdateError('http', str(error)))
        threading.Thread(target=work, daemon=True).start()

    def _on_fetched(self, result):
        self._checking = False
        if isinstance(result, releases.UpdateError):
            self._error = self.t('upd_err_' + result.kind, detail=result.detail)
        else:
            self.release = {'tag': result['tag'], 'url': result['url'], 'body': result['body'][:20000],
                            'published': result['published'], 'assets': list(result.get('assets') or [])[:20],
                            'checked': datetime.date.today().isoformat()}
            self.backend.settings['update_seen'] = self.release
            self._save()
        self.changed.emit()

    @Slot()
    def download(self):
        url = (self.release or {}).get('url') or releases.RELEASES_URL
        if not url.startswith(releases.RELEASE_PREFIX):
            url = releases.RELEASES_URL
        if 'open_url' in self.probes:
            self.probes['open_url'](url)
        else:
            tlg_run.open_external(url)

    # -- download and install (packaged builds) ------------------------------------------------------
    def frozen(self):
        return self.probes['frozen']() if 'frozen' in self.probes else tlg_run.FROZEN

    def port_dir(self):
        return Path(self.probes['port_dir']() if 'port_dir' in self.probes else tlg_run.PORT_DIR)

    def exe_name(self):
        return self.probes['exe']() if 'exe' in self.probes else Path(sys.executable).name

    @Property(bool, notify=changed)
    def packaged(self):
        return bool(self.frozen())

    @Property(bool, notify=changed)
    def busy(self):
        return self._phase in ('download', 'install')

    @Property(bool, notify=changed)
    def canInstall(self):
        """A newer release with a package for this platform, in a packaged build, nothing running."""
        if not self.frozen() or self._checking or self._phase or not self.available:
            return False
        try:
            updater.pick_assets(self.release)
        except releases.UpdateError:
            return False
        return True

    @Property(bool, notify=changed)
    def canRestart(self):
        return self._phase == 'ready'

    @Property(bool, notify=changed)
    def canCancel(self):
        return self._phase == 'download'

    @Property(float, notify=changed)
    def progress(self):
        done, total = self._progress
        return done / total if total else 0.0

    @Property(str, notify=changed)
    def progressText(self):
        if self._phase == 'download':
            done, total = self._progress
            return self.t('upd_downloading', done=_mb(done), total=_mb(total),
                          pct=int(100 * done / total) if total else 0)
        if self._phase == 'install':
            return self.t('upd_installing')
        return ''

    @Property(str, notify=changed)
    def installHint(self):
        """Why there is no "Download and install" here (a git checkout), or '' when there is."""
        return '' if self.frozen() else self.t('upd_source_hint')

    @Property('QVariantMap', notify=dialogChanged)
    def dialog(self):
        return self._dialog

    def _ask(self, title, body, buttons, handlers, lines=()):
        self._handlers = handlers
        self._dialog = {'open': True, 'title': title, 'body': body, 'lines': list(lines),
                        'buttons': [{'id': i, 'label': l, 'tone': t} for i, l, t in buttons]}
        self.dialogChanged.emit()

    @Slot(str)
    def answer(self, button):
        handler = self._handlers.get(button)
        self._dialog, self._handlers = {}, {}
        self.dialogChanged.emit()
        if handler:
            handler()

    def data_dir(self):
        return Path(self.probes['data_dir']() if 'data_dir' in self.probes else tlg_run.user_dir())

    def _fail(self, error):
        self._phase, self._progress = '', (0, 0)
        self._error = self.t('upd_err_' + error.kind, detail=error.detail)
        self.changed.emit()

    @Slot()
    def install(self):
        """Step 1: ask before downloading (size, where it goes, what stays)."""
        if not self.frozen() or self._phase:
            return
        try:
            package, _ = updater.pick_assets(self.release)
        except releases.UpdateError as error:
            self._fail(error)
            return
        port = self.port_dir()
        target = updater.target_folder(port, package['name'], self.release['tag'])
        data = updater.data_to_copy(port, self.data_dir())
        lines = [self.t('upd_ask_where', folder=str(target)), self.t('upd_ask_old', folder=str(port)),
                 self.t('upd_ask_data_copy' if data else 'upd_ask_data_kept', folder=str(self.data_dir()))]
        self._ask(self.t('upd_ask_download_title'),
                  self.t('upd_ask_download', tag=self.release['tag'], size=_mb(package['size'])),
                  [('yes', self.t('upd_download_now'), 'primary'), ('no', self.t('upd_cancel'), 'ghost')],
                  {'yes': self._start_download}, lines)

    def _start_download(self):
        package, sums_asset = updater.pick_assets(self.release)
        port, version = self.port_dir(), self.installed()
        data = updater.data_to_copy(port, self.data_dir())
        archive = port.parent / f'.iss-update-{package["name"]}'
        opener = self.probes.get('opener')
        self._cancel.clear()
        self._phase, self._progress, self._error = 'download', (0, package['size']), ''
        self.changed.emit()

        def work():
            try:
                need = updater.needed_bytes(package['size'], data)
                if updater.free_bytes(port.parent) < need:
                    raise releases.UpdateError('space', _mb(need))
                sums = updater.fetch_sums(sums_asset, version, opener) if sums_asset else None
                digest = updater.download(package, archive, version, opener,
                                          progress=lambda d, t: self.progressed.emit((d, t)),
                                          cancelled=self._cancel.is_set)
                try:
                    verified = updater.verify(package['name'], digest, sums)
                except releases.UpdateError:
                    archive.unlink(missing_ok=True)
                    raise
                self.stepDone.emit(('downloaded', (archive, verified)))
            except releases.UpdateError as error:
                self.stepDone.emit(error)
            except Exception as error:    # never leave the screen stuck on "downloading"
                self.stepDone.emit(releases.UpdateError('write', str(error)))
        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def cancelDownload(self):
        self._cancel.set()

    def _on_progress(self, value):
        if self._phase == 'download':
            self._progress = value
            self.changed.emit()

    def _on_step(self, result):
        if isinstance(result, releases.UpdateError):
            self._fail(result)
            return
        step, value = result
        if step == 'downloaded':
            self._archive, self._verified = value
            self._phase = ''
            self.changed.emit()
            self._ask_install()
        elif step == 'installed':
            self._new_dir, self._phase = value, 'ready'
            self.changed.emit()
            self._ask_restart()

    def _ask_install(self):
        """Step 2: the package is here and checked; ask before installing it."""
        package, _ = updater.pick_assets(self.release)
        target = updater.target_folder(self.port_dir(), package['name'], self.release['tag'])
        self._ask(self.t('upd_ask_install_title'),
                  self.t('upd_ask_install_sha' if self._verified else 'upd_ask_install_size',
                         tag=self.release['tag'], folder=str(target)),
                  [('yes', self.t('upd_install_now'), 'primary'), ('no', self.t('upd_cancel'), 'ghost')],
                  {'yes': self._start_install, 'no': self._discard})

    def _discard(self):
        if self._archive:
            Path(self._archive).unlink(missing_ok=True)
        self._archive = None

    def _start_install(self):
        package, _ = updater.pick_assets(self.release)
        archive, port, tag = self._archive, self.port_dir(), self.release['tag']
        exe, data = self.exe_name(), self.data_dir()
        self._phase, self._error = 'install', ''
        self.changed.emit()

        def work():
            try:
                folder = updater.install(archive, port, package['name'], tag, exe, data)
                self.stepDone.emit(('installed', folder))
            except releases.UpdateError as error:
                self.stepDone.emit(error)
            except Exception as error:
                self.stepDone.emit(releases.UpdateError('write', str(error)))
            finally:
                Path(archive).unlink(missing_ok=True)
        threading.Thread(target=work, daemon=True).start()

    def _ask_restart(self):
        """Step 3: offer to start the new version; the old folder stays to go back."""
        self._ask(self.t('upd_ask_restart_title'),
                  self.t('upd_ask_restart', folder=str(self._new_dir), old=str(self.port_dir())),
                  [('yes', self.t('upd_restart_now'), 'primary'), ('no', self.t('upd_later'), 'ghost')],
                  {'yes': self.restart})

    @Slot()
    def restart(self):
        if self._phase != 'ready' or not self._new_dir:
            return
        try:
            if 'launch' in self.probes:
                self.probes['launch'](self._new_dir)
            else:
                updater.launch(self._new_dir, self.exe_name(), tlg_run.desktop_env(), tlg_run.detach_options())
        except OSError as error:
            self._error, self._phase = self.t('upd_err_launch', detail=f'{self._new_dir}: {error}'), ''
            self.changed.emit()
            return
        if 'quit' in self.probes:
            self.probes['quit']()
        else:
            self.backend._quit_app()


def _mb(size):
    return f'{size / 2 ** 20:.0f} MB' if size >= 2 ** 20 else f'{size / 1024:.0f} KB'
