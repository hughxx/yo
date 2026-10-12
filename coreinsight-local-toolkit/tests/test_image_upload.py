import json
import unittest
from io import BytesIO
from unittest.mock import patch

import requests
from PIL import Image

from coreinsight_local_toolkit.image_upload import upload


def response(status):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps({'url': 'https://images.test/small.jpg'}).encode()
    return result


class ImageUploadTests(unittest.TestCase):
    def test_413_compresses_image_and_retries_the_exact_upload_endpoint(self):
        buffer = BytesIO()
        Image.new('RGBA', (4000, 1000), (255, 0, 0, 100)).save(buffer, format='PNG')
        with patch('coreinsight_local_toolkit.image_upload.requests.post',
                   side_effect=[response(413), response(200)]) as post:
            url, name, content = upload('https://gateway.test/image/upload',
                                        'image.png', buffer.getvalue())
        self.assertEqual('https://images.test/small.jpg', url)
        self.assertEqual('image.jpg', name)
        image = Image.open(BytesIO(content))
        self.assertEqual('JPEG', image.format)
        self.assertLessEqual(max(image.size), 3000)
        self.assertLess(len(content), 800_000)
        self.assertEqual(2, post.call_count)
        self.assertTrue(all(item.args[0] == 'https://gateway.test/image/upload'
                            for item in post.call_args_list))

    def test_oversized_archive_is_not_retried_as_an_image(self):
        with patch('coreinsight_local_toolkit.image_upload.requests.post',
                   return_value=response(413)) as post:
            with self.assertRaisesRegex(RuntimeError, '超过上传服务大小限制'):
                upload('https://gateway.test/image/upload', 'logs.zip', b'archive')
        post.assert_called_once()

    def test_missing_upload_route_has_actionable_error(self):
        with patch('coreinsight_local_toolkit.image_upload.requests.post',
                   return_value=response(404)):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 404'):
                upload('https://gateway.test/missing', 'image.png', b'image')
