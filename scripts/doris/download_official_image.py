"""Download the official Docker image on Windows for import into isolated WSL.

Only Docker Hub's apache/doris repository is used. Every manifest and blob is
verified by SHA-256. Anonymous registry tokens remain in memory.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import tarfile
import threading
import time
import urllib.request

REGISTRY = 'https://registry-1.docker.io/v2/apache/doris/'
TAG = 'all-in-one-4.1.3'
ACCEPT = ','.join(['application/vnd.oci.image.index.v1+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.docker.distribution.manifest.v2+json'])


def verified(data, digest):
    if 'sha256:' + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('SHA-256 mismatch: ' + digest)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:apache/doris:pull', timeout=60) as response:
        token = json.load(response)['token']
    headers = {'Authorization': 'Bearer ' + token, 'Accept': ACCEPT}

    def get_manifest(ref):
        with urllib.request.urlopen(urllib.request.Request(REGISTRY + 'manifests/' + ref, headers=headers), timeout=90) as response:
            data = response.read()
            digest = response.headers.get('Docker-Content-Digest')
        if ref.startswith('sha256:'):
            verified(data, ref)
        elif digest:
            verified(data, digest)
        return json.loads(data)

    index = get_manifest(TAG)
    platform = next(m for m in index['manifests'] if m.get('platform') == {'architecture': 'amd64', 'os': 'linux'})
    manifest = get_manifest(platform['digest'])
    print('Official linux/amd64 manifest: ' + platform['digest'], flush=True)
    print('Compressed layer bytes: ' + str(sum(layer['size'] for layer in manifest['layers'])), flush=True)

    def fetch_blob(blob):
        digest = blob['digest']
        path = args.directory / digest.split(':')[1]
        if path.exists() and path.stat().st_size == blob['size']:
            with path.open('rb') as file:
                if 'sha256:' + hashlib.file_digest(file, 'sha256').hexdigest() == digest:
                    return path
        for attempt in range(3):
            try:
                if blob['size'] > 128 * 1024 * 1024:
                    # Bounded ranges work through network gateways that buffer
                    # a full large response before returning the first byte.
                    with path.open('wb') as file:
                        file.truncate(blob['size'])
                    step = 8 * 1024 * 1024
                    progress = [0]
                    lock = threading.Lock()
                    def fetch_range(start):
                        end = min(start + step, blob['size']) - 1
                        request = urllib.request.Request(REGISTRY + 'blobs/' + digest,
                            headers={**headers, 'Range': f'bytes={start}-{end}'})
                        with urllib.request.urlopen(request, timeout=90) as response:
                            if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{blob["size"]}':
                                raise ValueError('Unexpected ranged response')
                            chunk = response.read(end - start + 2)
                        if len(chunk) != end - start + 1:
                            raise ValueError('Truncated range')
                        with path.open('r+b') as file:
                            file.seek(start)
                            file.write(chunk)
                        with lock:
                            progress[0] += len(chunk)
                            if progress[0] // (64 * 1024 * 1024) != (progress[0] - len(chunk)) // (64 * 1024 * 1024):
                                print('Range progress ' + digest[:23] + ': ' + str(progress[0]) + '/' + str(blob['size']), flush=True)
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        list(pool.map(fetch_range, range(0, blob['size'], step)))
                else:
                    request = urllib.request.Request(REGISTRY + 'blobs/' + digest, headers=headers)
                    with urllib.request.urlopen(request, timeout=120) as response, path.open('wb') as file:
                        while chunk := response.read(1024 * 1024):
                            file.write(chunk)
                with path.open('rb') as file:
                    actual = 'sha256:' + hashlib.file_digest(file, 'sha256').hexdigest()
                if path.stat().st_size != blob['size'] or actual != digest:
                    raise ValueError('Blob size or SHA-256 mismatch: ' + digest)
                print('Verified blob: ' + digest[:23] + ' (' + str(blob['size']) + ' bytes)', flush=True)
                return path
            except Exception as error:
                if attempt == 2:
                    raise
                print('Retry blob ' + digest[:23] + ': ' + type(error).__name__, flush=True)
                time.sleep(2)

    blobs = [manifest['config']] + manifest['layers']
    with ThreadPoolExecutor(max_workers=3) as pool:
        files = list(pool.map(fetch_blob, blobs))
    config_name = manifest['config']['digest'].split(':')[1] + '.json'
    layer_names = [layer['digest'].split(':')[1] + '/layer.tar' for layer in manifest['layers']]
    entry = [{'Config': config_name, 'RepoTags': ['apache/doris:' + TAG], 'Layers': layer_names}]
    archive = args.directory / ('apache-doris-' + TAG + '-amd64.tar')
    with tarfile.open(archive, 'w') as tar:
        tar.add(files[0], arcname=config_name)
        for file, name in zip(files[1:], layer_names):
            # Docker's layer loader detects gzip itself; preserve verified blobs.
            tar.add(file, arcname=name)
        data = json.dumps(entry).encode('utf-8')
        info = tarfile.TarInfo('manifest.json')
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (args.directory / 'image-source.json').write_text(json.dumps({
        'repository': 'apache/doris', 'tag': TAG, 'platform': 'linux/amd64',
        'manifestDigest': platform['digest'], 'manifest': manifest,
        'archiveBytes': archive.stat().st_size}, indent=2) + '\n', encoding='utf-8')
    print('DOCKER_ARCHIVE_READY: ' + str(archive), flush=True)


if __name__ == '__main__':
    main()
