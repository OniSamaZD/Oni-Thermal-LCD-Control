from __future__ import annotations

import copy

from .profile_package import normalize_profile_name
from .settings import AppSettings, DisplayProfile

MAX_USER_PROFILES = 20


def user_profile_count(settings: AppSettings, device_id: str | None = None) -> int:
    return sum(name != "Default" and (device_id is None or device_id in devices) for name,devices in settings.profiles.items())


def save_device_profile(settings: AppSettings, name: str, device_id: str,
                        profile: DisplayProfile, *, overwrite: bool = False) -> str:
    name = normalize_profile_name(name)
    exists = name in settings.profiles and device_id in settings.profiles[name]
    if exists and not overwrite:
        raise FileExistsError(name)
    if not exists and name != "Default" and user_profile_count(settings,device_id) >= MAX_USER_PROFILES:
        raise OverflowError("You can save up to 20 profiles. Delete an existing profile before creating another.")
    settings.profiles.setdefault(name, {})[device_id] = copy.deepcopy(profile)
    settings.active_profile = name
    return name


def rename_profile(settings: AppSettings, old: str, new: str, *, overwrite: bool = False) -> str:
    new = normalize_profile_name(new)
    if old not in settings.profiles:
        raise KeyError(old)
    if new != old and new in settings.profiles and not overwrite:
        raise FileExistsError(new)
    value = settings.profiles.pop(old)
    if new in settings.profiles:
        settings.profiles[new].update(value)
    else:
        settings.profiles[new] = value
    if settings.active_profile == old:
        settings.active_profile = new
    return new


def duplicate_profile(settings: AppSettings, source: str, target: str) -> str:
    target = normalize_profile_name(target)
    if target in settings.profiles:
        raise FileExistsError(target)
    if target != "Default" and user_profile_count(settings) >= MAX_USER_PROFILES:
        raise OverflowError("You can save up to 20 profiles. Delete an existing profile before creating another.")
    settings.profiles[target] = copy.deepcopy(settings.profiles[source])
    return target
