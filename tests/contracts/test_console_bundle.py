import hashlib
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from deployment.console_bundle import build_console_bundle, main
from deployment.release_artifacts import host_digest
from tests.fixtures.terraform_source import EXPECTED_MEMBERS, write_terraform_source


class ConsoleBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = write_terraform_source(self.root)
        schema = Path(__file__).resolve().parents[2] / 'infra/terraform/schema.yaml'
        (self.source / 'schema.yaml').write_bytes(schema.read_bytes())
        self.output = self.root / 'console.zip'
        self.release = dict(artifact_base='https://objectstorage.us-ashburn-1.oraclecloud.com/n/example/b/public/o/',
            release='a' * 40, host_digest=host_digest(self.root), image_id='sha256:' + 'b' * 64,
            image_sha256='c' * 64, image_bytes=123456)

    def test_checked_archive_pins_only_public_release_and_excludes_private_inputs(self):
        (self.source / 'secrets.tfvars').write_text('private-marker')
        digest = build_console_bundle(self.root, self.output, self.release)
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.namelist(), [*EXPECTED_MEMBERS, 'schema.yaml', 'console.auto.tfvars.json'])
            self.assertEqual(json.loads(archive.read('console.auto.tfvars.json')),
                             {'console_install': True, 'console_release': self.release})
            schema = json.loads(archive.read('schema.yaml'))
            self.assertEqual(schema['primaryOutputButton'], '${application_origin}')
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertNotIn(b'private-marker', self.output.read_bytes())

    def test_identical_input_is_deterministic_and_existing_output_is_preserved(self):
        build_console_bundle(self.root, self.output, self.release)
        second = self.root / 'second.zip'
        build_console_bundle(self.root, second, dict(reversed(list(self.release.items()))))
        self.assertEqual(self.output.read_bytes(), second.read_bytes())
        with self.assertRaises(FileExistsError):
            build_console_bundle(self.root, self.output, self.release)
        self.assertEqual(self.output.read_bytes(), second.read_bytes())

    def test_bad_or_private_descriptor_cannot_create_an_archive(self):
        cases = [
            {'artifact_base': 'https://example.com/private?token=hidden'},
            {'host_digest': 'd' * 64}, {'image_id': 'latest'},
            {'image_bytes': True}, {'image_bytes': 0}, {'image_bytes': 2**31 + 1},
            {'release': 'dev'}, {'image_sha256': 'wrong'}, {'runtime': {'password': 'hidden'}},
        ]
        for change in cases:
            with self.subTest(change=list(change)):
                with self.assertRaisesRegex(ValueError, 'Console release'):
                    build_console_bundle(self.root, self.output, self.release | change)
                self.assertFalse(self.output.exists())
        for value in (None, [], {}, self.release | {'artifact_base': None}):
            with self.subTest(value=type(value)):
                with self.assertRaisesRegex(ValueError, 'Console release'):
                    build_console_bundle(self.root, self.output, value)
                self.assertFalse(self.output.exists())

    def test_schema_and_source_must_be_regular_reviewed_files(self):
        schema = self.source / 'schema.yaml'
        schema.unlink()
        with self.assertRaises(ValueError):
            build_console_bundle(self.root, self.output, self.release)
        schema.symlink_to(self.source / 'outputs.tf')
        with self.assertRaises(ValueError):
            build_console_bundle(self.root, self.output, self.release)
        self.assertFalse(self.output.exists())

    def test_cli_rejects_malformed_bounded_descriptors_with_fixed_guidance(self):
        path = self.root / 'descriptor.json'
        cases = ('not json', '{"version":1,"version":2}', '[' * 4000 + ']' * 4000, 'x' * 16385)
        for content in cases:
            with self.subTest(size=len(content)):
                path.write_text(content)
                stderr = StringIO()
                with patch('sys.argv', ['console_bundle', '--descriptor', str(path), '--output', str(self.output)]):
                    with redirect_stderr(stderr), self.assertRaises(SystemExit) as result:
                        main()
                self.assertEqual(result.exception.code, 2)
                self.assertEqual(stderr.getvalue(), 'error: Console package inputs are invalid or output already exists.\n')
                self.assertFalse(self.output.exists())


class ConsoleSchemaTests(unittest.TestCase):
    def test_guided_inputs_use_native_selectors_without_credential_fields(self):
        path = Path(__file__).resolve().parents[2] / 'infra/terraform/schema.yaml'
        schema = json.loads(path.read_text())
        variables = schema['variables']
        self.assertEqual(schema['schemaVersion'], '1.1.0')
        self.assertEqual(variables['compartment_ocid']['type'], 'oci:identity:compartment:id')
        self.assertEqual(variables['availability_domain']['type'], 'oci:identity:availabilitydomain:name')
        self.assertEqual(variables['image_ocid']['type'], 'string')
        self.assertFalse(variables['image_ocid']['visible'])
        self.assertFalse(variables['image_ocid'].get('required', False))
        visible = [name for group in schema['variableGroups'] if group.get('visible', True)
                   for name in group['variables']]
        self.assertNotIn('${image_ocid}', visible)
        groups = [name.removeprefix('${').removesuffix('}')
                  for group in schema['variableGroups'] for name in group['variables']]
        attributes = {name for value in variables.values() if value['type'] == 'object'
                      for name in value['attributes']}
        self.assertEqual(set(groups) | attributes, set(variables))
        for name in ('tenancy_ocid', 'region', 'application', 'console_release', 'console_install'):
            self.assertFalse(variables[name]['visible'])
        for name in ('password', 'demo_password', 'openai_api_key', 'anthropic_api_key', 'private_key'):
            self.assertNotIn(name, variables)
        self.assertEqual(schema['outputs']['settings_secret_ocid']['type'], 'ocid')

    def test_object_attributes_have_hidden_named_definitions_without_reusing_selectors(self):
        path = Path(__file__).resolve().parents[2] / 'infra/terraform/schema.yaml'
        variables = json.loads(path.read_text())['variables']
        expected = {
            'console_release': {'artifact_base', 'release', 'host_digest', 'image_id', 'image_sha256', 'image_bytes'},
            'application': {'version', 'tenancy_ocid', 'home_region', 'availability_domain', 'image_ocid'},
        }
        for object_name, names in expected.items():
            with self.subTest(object=object_name):
                attributes = [variables[name] for name in variables[object_name]['attributes']]
                self.assertEqual({value['actualName'] for value in attributes}, names)
                self.assertTrue(all(value['visible'] is False for value in attributes))
                for value in attributes:
                    kind = 'integer' if value['actualName'] in {'version', 'image_bytes'} else 'string'
                    self.assertEqual(value['type'], kind)
        self.assertEqual(variables['image_ocid']['type'], 'string')
        self.assertEqual(variables['availability_domain']['type'], 'oci:identity:availabilitydomain:name')

    def test_every_output_has_the_required_type_including_hidden_outputs(self):
        path = Path(__file__).resolve().parents[2] / 'infra/terraform/schema.yaml'
        outputs = json.loads(path.read_text())['outputs']
        for name, value in outputs.items():
            with self.subTest(output=name):
                expected = 'link' if name == 'application_origin' else 'ocid' if name.endswith('_ocid') else 'string'
                self.assertEqual(value['type'], expected)
