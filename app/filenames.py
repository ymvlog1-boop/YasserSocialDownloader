from pathlib import Path
import re


def clean_gallery_suffix(filename):
    """Remove gallery-dl's mandatory .1 suffix; number only actual collisions."""
    source = Path(filename)
    if not source.is_file() or not source.stem.endswith('.1'):
        return filename
    base = source.stem[:-2]
    if not base:
        return filename
    return _rename_with_collision_number(source, base)


def clean_video_suffix(filename):
    """Remove the internal video ID after download, retaining distinct titles."""
    source = Path(filename)
    if not source.is_file() or '___YID___' not in source.stem:
        return filename
    base, _, identity = source.stem.rpartition('___YID___')
    if not base or not identity:
        return filename
    return _rename_with_collision_number(source, base)


def _rename_with_collision_number(source, base):
    # TikTok sometimes supplies a generated ID label when a post has no text.
    if re.fullmatch(r'TikTok (?:video|audio) #\d+', base, re.IGNORECASE):
        base = 'منشور'
    target = source.with_name(base + source.suffix)
    number = 2
    while target.exists():
        target = source.with_name(f'{base} ({number}){source.suffix}')
        number += 1
    try:
        source.rename(target)
    except OSError:
        return filename
    return str(target)
