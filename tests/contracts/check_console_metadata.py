"""Check actual Terraform mock metadata against the real host parser (no OCI calls)."""

import base64
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from infra.terraform.host.console_contract import parse_installation


def check(path):
    count, summary, diagnostics = 0, None, []
    with Path(path).open() as stream:
        for line in stream:
            event = json.loads(line)
            if event.get('type') == 'diagnostic':
                diagnostics.append(event['diagnostic']['summary'] + ': ' + event['diagnostic']['detail'])
            if event.get('type') == 'test_summary':
                summary = event['test_summary']['status']
                print(event['@message'])
            if event.get('type') != 'test_state':
                continue
            resources = event['test_state']['root_module']['resources']
            for resource in resources:
                if resource['address'] != 'oci_core_instance.app[0]':
                    continue
                metadata = resource['values']['metadata']
                if 'energy_ai_install' not in metadata:
                    continue
                cloud = gzip.decompress(base64.b64decode(metadata['user_data'])).decode()
                # Get the helper hash from the actual packaged host.json, not the desired manifest.
                configurations = []
                for entry in cloud.splitlines():
                    if entry.startswith('- "content": "{'):
                        content = json.loads(json.loads(entry.split(': ', 1)[1]))
                        if set(content) == {'version', 'host_digest', 'region', 'namespace', 'bucket'}:
                            configurations.append(content)
                assert len(configurations) == 1
                helper_digest = configurations[0]['host_digest']
                desired = metadata['energy_ai_install'].encode()
                installation = parse_installation(desired,
                    b'[{"privateIp":"10.40.1.10","subnetCidrBlock":"10.40.1.0/24"}]',
                    helper_digest, 'us-ashburn-1')
                manifest = json.loads(installation.manifest)
                assert manifest['runtime']['backend_host'] == '10.40.1.10:8080'
                custom = event.get('@testrun') in ('configured_models', 'configured_models_repeat')
                expected_models = ({'oci': 'oci.fixture:2', 'openai': 'openai_fixture-2',
                                    'anthropic': 'anthropic-fixture-2'} if custom else {
                    'oci': 'google.gemini-2.5-flash', 'openai': 'gpt-4.1-2025-04-14',
                    'anthropic': 'claude-haiku-5-5'})
                assert manifest['runtime']['model_ids'] == expected_models
                assert set(manifest['runtime']['secret_ids']) == {'settings'}
                assert len(json.dumps(metadata).encode()) < 32000
                count += 1
    if summary != 'pass':
        print('\n'.join(diagnostics))
        raise AssertionError('Terraform mock suite did not finish successfully.')
    if count < 3:
        raise AssertionError('Expected first install, unchanged reapply and retry-generation metadata.')
    print(f'Validated {count} Terraform Console metadata records with the real host parser.')


if __name__ == '__main__':
    check(sys.argv[1])
