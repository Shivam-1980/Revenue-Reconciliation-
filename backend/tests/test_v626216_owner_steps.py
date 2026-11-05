"""Owner security steps (V62.6.216): the checklist must tell a second disk from a second drive letter."""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services import security_posture as sp
import owner_security_steps as steps


def test_env_value_is_replaced_or_added():
    assert steps.set_env_value("A=1\nEKO_BACKUP_DIR=old\nB=2\n", "EKO_BACKUP_DIR", "X:/b") == "A=1\nEKO_BACKUP_DIR=X:/b\nB=2\n"
    assert steps.set_env_value("A=1\n", "EKO_BACKUP_DIR", "X:/b") == "A=1\nEKO_BACKUP_DIR=X:/b\n"
    assert steps.set_env_value("# EKO_BACKUP_DIR=old\n", "EKO_BACKUP_DIR", "Z").splitlines() == ["# EKO_BACKUP_DIR=old", "EKO_BACKUP_DIR=Z"]


def test_onedrive_and_network_folders_are_a_second_copy():
    assert sp.backup_is_off_disk(r"C:\Users\me\OneDrive\EkoBackups")[0] is True
    assert sp.backup_is_off_disk(r"\\nas\share\eko")[0] is True
    assert sp.backup_is_off_disk("")[0] is False


def test_another_drive_letter_on_the_same_physical_disk_is_not_enough(monkeypatch):
    monkeypatch.setattr(sp, "physical_disk", lambda p: 0)
    off, why = sp.backup_is_off_disk(r"E:\backups", r"D:\data")
    assert off is False and "physical disk 0" in why


def test_a_different_physical_disk_counts(monkeypatch):
    monkeypatch.setattr(sp, "physical_disk", lambda p: 1 if str(p).startswith("E:") else 0)
    assert sp.backup_is_off_disk(r"E:\backups", r"D:\data")[0] is True
