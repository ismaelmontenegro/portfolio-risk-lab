import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from eodhd_client import Client, load_token

class ClientTests(unittest.TestCase):
    def test_cache_avoids_repeat_request_and_omits_token(self):
        with tempfile.TemporaryDirectory() as folder:
            client=Client('private-token',folder,max_calls=1)
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'[{"date":"2026-01-02"}]')) as request:
                one=client.get('eod/TEST.US')
                two=client.get('eod/TEST.US')
                self.assertEqual(one,two);self.assertEqual(request.call_count,1)
            self.assertNotIn('private-token',next(Path(folder).glob('*.json')).read_text())
    def test_error_redacts_url_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('urllib.request.urlopen',side_effect=HTTPError('https://example/?api_token=secret',401,'bad',{},None)) as request:
                with self.assertRaisesRegex(RuntimeError,'HTTP 401') as error:Client('secret',folder).get('eod/TEST.US')
                self.assertNotIn('secret',str(error.exception));self.assertEqual(request.call_count,1)
    def test_call_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'cap'):Client('token',folder,max_calls=0).get('search/TEST')
    def test_token_loader(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'.env';path.write_text('EODHD_API_TOKEN="example"')
            with patch.dict('os.environ',{},clear=True):self.assertEqual(load_token(path),'example')

if __name__=='__main__':unittest.main()
