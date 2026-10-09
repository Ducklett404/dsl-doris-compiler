"""Validate atomic Stream Load counters; never accept filtered or partial loads."""
import json
from pathlib import Path
import sys


def verify(response, expected_rows):
    if response.get('Status') not in ('Success', 'Publish Timeout'):
        raise ValueError('Stream Load rejected: ' + str(response.get('Message', response.get('Status'))))
    for key, expected in [('NumberTotalRows', expected_rows), ('NumberLoadedRows', expected_rows),
                          ('NumberFilteredRows', 0), ('NumberUnselectedRows', 0)]:
        value = response.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            raise ValueError(f'{key}: expected {expected}, got {value}')
    # Publish Timeout has committed: caller waits for visible counts and never
    # retries the transaction with another label.
    return response['Status']


if __name__ == '__main__':
    print(verify(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')), int(sys.argv[2])))
