# SPDX-License-Identifier: GPL-2.0-or-later
"""Disk-level update/rollback tests; never use the player's installation."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import update_install as ui


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='iss-update-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = self.root / 'instalação com espaços'
        self.stage = self.root / 'work' / 'payload'
        self.target.mkdir()
        self.stage.mkdir(parents=True)
        for root, version in ((self.target, 'old'), (self.stage, 'new')):
            (root / 'launcher.exe').write_text(version)
            (root / 'out').mkdir()
            (root / 'out' / 'runtime.dll').write_text(version)
        for name in ('user/savedata/slot/dis.dat', 'user/cache/pipeline.bin', 'game/eboot.bin', 'mods/local.txt'):
            path = self.target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('player')
        ui.write_manifest(self.stage, 'new')

    def prepare(self, **kwargs):
        return ui.prepare(self.stage, self.target, 'new', exe_name='launcher.exe', **kwargs)

    def assert_personal(self):
        for name in ('user/savedata/slot/dis.dat', 'user/cache/pipeline.bin', 'game/eboot.bin', 'mods/local.txt'):
            self.assertEqual((self.target / name).read_text(), 'player')

    def test_apply_same_path_and_restore_without_reverting_saves(self):
        tx = self.prepare()
        ui.apply(tx)
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'new')
        self.assert_personal()
        (self.target / 'user/savedata/slot/dis.dat').write_text('new progress')
        ui.recover(tx)
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'old')
        self.assertEqual((self.target / 'user/savedata/slot/dis.dat').read_text(), 'new progress')
        ui.recover(tx)  # idempotent

    def test_corrupt_payload_refused_before_writing(self):
        (self.stage / 'launcher.exe').write_text('corrupt')
        with self.assertRaises(ui.InstallError):
            self.prepare()
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'old')

    def test_protected_payload_and_escape_paths_refused(self):
        manifest = json.loads((self.stage / ui.MANIFEST).read_text())
        entry = manifest['files'][0]
        for name in ('../outside', 'user/evil', 'mods/evil', 'game/eboot.bin', 'C:/escape', 'out/a:stream', 'CON', 'out/../evil'):
            with self.subTest(name=name):
                changed = dict(manifest, files=[dict(entry, path=name)])
                (self.stage / ui.MANIFEST).write_text(json.dumps(changed))
                with self.assertRaises(ui.InstallError):
                    self.prepare(protected=(self.target / 'game',))

    def test_modified_old_managed_file_is_not_overwritten(self):
        ui.write_manifest(self.target, 'old', paths=['launcher.exe', 'out/runtime.dll'])
        (self.target / 'launcher.exe').write_text('user change')
        with self.assertRaises(ui.InstallError):
            self.prepare()

    def test_new_file_collision_is_not_overwritten(self):
        ui.write_manifest(self.target, 'old', paths=['launcher.exe', 'out/runtime.dll'])
        (self.stage / 'added.txt').write_text('packaged')
        (self.target / 'added.txt').write_text('personal')
        ui.write_manifest(self.stage, 'new')
        with self.assertRaises(ui.InstallError):
            self.prepare()

    def test_failure_at_every_replace_restores_old_files(self):
        for fail_at in range(3):  # two files and the installed manifest
            with self.subTest(fail_at=fail_at):
                tx = self.prepare()
                def fail(index):
                    if index == fail_at:
                        raise OSError('simulated locked file')
                with self.assertRaises(ui.InstallError):
                    ui.apply(tx, after_replace=fail)
                self.assertEqual((self.target / 'launcher.exe').read_text(), 'old')
                self.assertEqual((self.target / 'out/runtime.dll').read_text(), 'old')
                self.assert_personal()

    def test_process_death_recovery_uses_write_ahead_journal(self):
        tx = self.prepare()
        with self.assertRaises(SystemExit):
            ui.apply(tx, after_replace=lambda _: sys.exit(9))
        ui.recover(tx)
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'old')
        self.assert_personal()

    def test_obsolete_managed_file_removed_and_rollback_restores_it(self):
        (self.target / 'obsolete.dll').write_text('old lib')
        ui.write_manifest(self.target, 'old', paths=['launcher.exe', 'out/runtime.dll', 'obsolete.dll'])
        tx = self.prepare()
        ui.apply(tx)
        self.assertFalse((self.target / 'obsolete.dll').exists())
        ui.recover(tx)
        self.assertEqual((self.target / 'obsolete.dll').read_text(), 'old lib')

    def test_source_checkout_and_missing_space_refused(self):
        (self.target / '.git').mkdir()
        with self.assertRaises(ui.InstallError):
            self.prepare()
        (self.target / '.git').rmdir()
        with mock.patch.object(ui.shutil, 'disk_usage', return_value=mock.Mock(free=0)):
            with self.assertRaises(ui.InstallError):
                self.prepare()

    def test_exclusive_install_lock(self):
        with ui.install_lock(self.target):
            with self.assertRaises(ui.InstallError):
                with ui.install_lock(self.target):
                    pass

    def test_change_after_prepare_is_refused(self):
        tx = self.prepare()
        (self.target / 'launcher.exe').write_text('changed after prepare')
        with self.assertRaises(ui.InstallError):
            ui.apply(tx)
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'changed after prepare')

    def test_second_update_prunes_older_backup_and_rolls_back_to_the_previous(self):
        ui.apply(self.prepare())
        ui.confirm(self.target)
        second = self.root / '.iss-update-b' / 'payload'
        second.mkdir(parents=True)
        (second / 'launcher.exe').write_text('newer')
        (second / 'out').mkdir()
        (second / 'out' / 'runtime.dll').write_text('newer')
        ui.write_manifest(second, 'newer')
        tx = ui.prepare(second, self.target, 'newer', exe_name='launcher.exe')
        ui.apply(tx)
        ui.confirm(self.target)
        self.assertFalse((self.root / '.iss-update-a').exists())   # only the newest backup is kept
        (self.target / 'user/savedata/slot/dis.dat').write_text('progress after update')
        ui.recover(tx)
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'new')
        self.assertEqual((self.target / 'user/savedata/slot/dis.dat').read_text(), 'progress after update')

    def test_external_game_and_data_are_byte_identical_after_apply(self):
        game, data = self.root / 'jogo externo', self.root / 'dados externos'
        for folder in (game, data):
            folder.mkdir()
            (folder / 'eboot.bin').write_text('game')
            (folder / 'slot.dat').write_text('save')
        before = {p: ui._hash(p) for p in (*game.rglob('*'), *data.rglob('*')) if p.is_file()}
        ui.apply(self.prepare(protected=(game, data)))
        after = {p: ui._hash(p) for p in (*game.rglob('*'), *data.rglob('*')) if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'new')


if __name__ == '__main__':
    unittest.main()
