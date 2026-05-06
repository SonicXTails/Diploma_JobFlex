"""Shared demo / seed helpers for binary image assets."""
from __future__ import annotations

from io import BytesIO


def demo_evidence_png_bytes() -> bytes:
    """Small valid PNG for moderator deletion evidence placeholders.

    Older seeds embedded a minimal base64 PNG that Pillow 10+ rejects
    ("broken data stream when reading image file").
    """
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', (24, 24), (200, 70, 70)).save(buf, format='PNG')
    return buf.getvalue()


def repair_moderator_deletion_photo_files() -> int:
    """Re-save evidence files that Pillow cannot open. Returns number of rows updated."""
    from pathlib import PurePosixPath

    from django.core.files.base import ContentFile
    from PIL import Image

    from vacancies.models import ModeratorDeletionPhoto

    good = demo_evidence_png_bytes()
    updated = 0
    for ph in ModeratorDeletionPhoto.objects.iterator():
        try:
            path = ph.image.path
        except Exception:
            continue
        try:
            with Image.open(path) as im:
                im.load()
        except Exception:
            name = PurePosixPath(ph.image.name or 'evidence.png').name
            ph.image.save(name, ContentFile(good), save=True)
            updated += 1
    return updated
