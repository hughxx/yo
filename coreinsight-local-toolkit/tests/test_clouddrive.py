import threading
import unittest
from unittest.mock import call, patch

import requests

from coreinsight_local_toolkit.clouddrive import CloudDriveDownloader, CloudDriveRateLimited
from coreinsight_local_toolkit.config import Settings


def response(status=200, body=b'file', retry_after=None):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result._content_consumed = True
    if retry_after is not None:
        result.headers['Retry-After'] = str(retry_after)
    return result


class CloudDriveTests(unittest.TestCase):
    def setUp(self):
        self.downloader = CloudDriveDownloader(Settings(
            clouddrive_account='account', clouddrive_password='secret'))
        self.sleep = self.enterContext(patch(
            'coreinsight_local_toolkit.clouddrive.time.sleep'))
        self.post = self.enterContext(patch(
            'coreinsight_local_toolkit.clouddrive.requests.post'))

    def test_reuses_token_for_multiple_attachments(self):
        self.post.side_effect = [response(body=b'{"token":"token"}'),
                                 response(body=b'first'), response(body=b'second')]
        self.assertEqual(b'first', self.downloader.download('one', 'code'))
        self.assertEqual(b'second', self.downloader.download('two', 'code'))
        self.assertEqual(3, self.post.call_count)
        self.assertEqual('token', self.post.call_args.kwargs['headers']['Authorization'])

    def test_retries_429_after_requested_delay(self):
        self.post.side_effect = [response(body=b'{"token":"token"}'),
                                 response(429, retry_after=3), response()]
        self.assertEqual(b'file', self.downloader.download('one', 'code'))
        self.assertIn(call(3.0), self.sleep.call_args_list)
        self.assertEqual(3, self.post.call_count)

    def test_sustained_rate_limit_stops_requests_for_following_attachments(self):
        self.post.side_effect = [response(body=b'{"token":"token"}'),
                                 response(429), response(429), response(429)]
        with self.assertRaises(CloudDriveRateLimited):
            self.downloader.download('one', 'code')
        with self.assertRaises(CloudDriveRateLimited):
            self.downloader.download('two', 'code')
        self.assertEqual(4, self.post.call_count)
        # A later task may try again after the cooldown expires.
        self.downloader._blocked_until = 0
        self.post.side_effect = [response()]
        self.assertEqual(b'file', self.downloader.download('three', 'code'))

    def test_long_retry_after_is_preserved_without_blocking_the_task(self):
        self.post.side_effect = [response(429, retry_after=120)]
        with self.assertRaisesRegex(CloudDriveRateLimited, '120'):
            self.downloader.download('one', 'code')
        self.assertEqual(1, self.post.call_count)
        self.assertNotIn(call(120.0), self.sleep.call_args_list)

    def test_retry_after_http_date_and_invalid_values(self):
        self.assertGreater(self.downloader._retry_delay(
            response(429, retry_after='Wed, 01 Jan 2100 00:00:00 GMT'), 0), 60)
        self.assertEqual(4, self.downloader._retry_delay(
            response(429, retry_after='invalid'), 1))

    def test_expired_token_is_refreshed_once(self):
        self.post.side_effect = [response(body=b'{"token":"old"}'), response(401),
                                 response(body=b'{"token":"new"}'), response()]
        self.assertEqual(b'file', self.downloader.download('one', 'code'))
        self.assertEqual(4, self.post.call_count)
        self.assertEqual('new', self.post.call_args.kwargs['headers']['Authorization'])

    def test_non_retryable_http_error_is_not_retried(self):
        self.post.side_effect = [response(403)]
        with self.assertRaises(requests.HTTPError):
            self.downloader.download('one', 'code')
        self.assertEqual(1, self.post.call_count)

    def test_cancel_during_rate_limit_wait_prevents_retry(self):
        cancel = threading.Event()

        def limited(*args, **kwargs):
            cancel.set()
            return response(429)

        self.post.side_effect = limited
        with self.assertRaisesRegex(RuntimeError, '任务已取消'):
            self.downloader.download('one', 'code', cancel)
        self.assertEqual(1, self.post.call_count)


if __name__ == '__main__':
    unittest.main()
