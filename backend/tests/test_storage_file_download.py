import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.features.auth import router as auth_router


class StorageFileDownloadTests(unittest.TestCase):
    def test_download_query_sets_attachment_disposition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "blog-images" / "blog-1" / "image.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"image")

            with (
                patch.object(auth_router, "settings", SimpleNamespace(storage_root=tmpdir)),
                patch.object(auth_router, "verify_storage_signature", return_value=True),
            ):
                response = asyncio.run(
                    auth_router.serve_storage_file(
                        "blog-images",
                        "blog-1/image.jpg",
                        exp=9_999_999_999,
                        sig="valid",
                        download=True,
                    )
                )

        disposition = response.headers.get("content-disposition", "")
        self.assertIn("attachment", disposition)
        self.assertIn("image.jpg", disposition)


if __name__ == "__main__":
    unittest.main()
