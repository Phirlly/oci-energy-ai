"""Opt-in public HTTPS journeys; never emit passwords, bill contents or model text."""

import hashlib
import json
from uuid import UUID, uuid4

from deployment.configuration import DeploymentError
from deployment.verify_bills import ExpectedFactsError, check_facts
from energy_ai.bills.schema import Candidate, Facts


CONTROLS = dict(power_kw=25.0, capacity_kwh=100.0, efficiency=0.9, target_kw=80.0)


class HostedVerifier:
    def __init__(self, client, config, password, release, deadline):
        self.client, self.config, self.password = client, config, password
        self.release, self.deadline = release, deadline
        self.headers = {'Origin': config.origin, 'X-Energy-Action': '1'}

    def _request(self, method, path, *, status=200, raw=False, **options):
        self.deadline.check()
        try:
            with self.client.stream(method, path, headers=self.headers, **options) as response:
                if response.status_code != status:
                    raise ValueError()
                chunks, count = [], 0
                for chunk in response.iter_bytes():
                    self.deadline.check()
                    count += len(chunk)
                    if count > 4 * 1024 * 1024:
                        raise ValueError()
                    chunks.append(chunk)
                payload = b''.join(chunks)
                if raw:
                    return payload
                return json.loads(payload)
        except Exception:
            raise DeploymentError('Hosted request failed; response details suppressed.') from None

    def _poll(self, path, *, document=False):
        while True:
            result = self._request('GET', path)
            job = result.get('job') if document else result
            if not isinstance(job, dict):
                raise DeploymentError('Hosted job response was invalid.')
            if job.get('status') == 'complete':
                return result
            if job.get('status') != 'running':
                raise DeploymentError('Hosted provider journey did not complete successfully.')
            self.deadline.pause()

    def _bills(self):
        pdf = self._request('GET', '/api/office/bill.pdf', raw=True)
        if not pdf.startswith(b'%PDF'):
            raise DeploymentError('Hosted illustrative PDF was invalid.')
        uploaded = self._request('POST', '/api/documents', status=201, content=pdf)
        if uploaded['approved_revision'] is not None or not uploaded['pages']:
            raise DeploymentError('Hosted PDF review did not preserve the review requirement.')
        self._request('DELETE', '/api/documents/' + uploaded['id'])
        example = self._request('POST', '/api/example', status=201)
        path = '/api/documents/' + example['id']
        self._request('POST', path + '/approve', json={'revision': example['revision']})
        insight = self._request('POST', '/api/insights', json={'revisions': {example['id']: example['revision']}})
        if insight['aggregate']['daily_kwh'] != '20.00' or insight['aggregate']['current_total'] != '91.50':
            raise DeploymentError('Hosted reviewed-bill arithmetic differs from the public fixture.')
        return path

    def _provider(self, provider, document_path):
        run = self._request('POST', '/api/office/runs', status=202, json=dict(
            request_key=str(uuid4()), provider=provider, consent=True, controls=CONTROLS, question='evaluate_battery'))
        run = self._poll('/api/office/runs/' + run['id'])
        result = run['result']
        if (result['usage']['tool_calls'] != 2 or result['usage']['model_requests'] < 2
                or result['energy']['baseline_total_usd'] != '6710.80'
                or result['savings']['scenario_total_usd'] != '6344.11'
                or {event.get('tool') for event in run['events'] if event.get('kind') == 'tool_finished'}
                   != {'inspect_office', 'simulate_selected_battery'}):
            raise DeploymentError('Hosted office tool evidence differs from expected results.')
        self._request('POST', document_path + '/extract', status=202, json={'provider': provider, 'consent': True})
        doc = self._poll(document_path, document=True)
        stage = 'job_metadata'
        try:
            if doc['approved_revision'] is not None or doc['job']['usage']['requests'] < 1:
                raise ValueError()
            stage = 'proposal_evidence'
            proposal = Candidate.model_validate(doc['proposal']).verify(doc['pages'])
            stage = 'proposal_facts'
            check_facts(proposal.facts, 0)
            stage = 'reviewed_facts'
            check_facts(Facts.model_validate(doc['facts']), 0)
        except ExpectedFactsError as error:
            diagnostics = json.dumps(error.diagnostics, sort_keys=True, allow_nan=False)
            raise DeploymentError(f'Hosted bill verification failed: provider={provider}; stage={stage}; '
                                  f'diagnostics={diagnostics}') from None
        except Exception:
            raise DeploymentError(f'Hosted bill verification failed: provider={provider}; stage={stage}; '
                                  'response details suppressed.') from None

    def _history(self):
        try:
            records = self._request('GET', '/api/office/runs')
            if not isinstance(records, list) or len(records) > 100:
                raise ValueError()
            seen, fingerprints = set(), {}
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError()
                identifier, status = record['id'], record['status']
                if (not isinstance(identifier, str) or str(UUID(identifier)) != identifier
                        or identifier in seen or status not in {'running', 'complete', 'failed', 'cancelled', 'interrupted'}):
                    raise ValueError()
                seen.add(identifier)
                if status == 'complete':
                    if not isinstance(record['result'], dict):
                        raise ValueError()
                    content = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
                    fingerprints[identifier] = hashlib.sha256(content).hexdigest()
            return fingerprints
        except Exception:
            raise DeploymentError('Hosted public history evidence was invalid; response details suppressed.') from None

    def check(self, *, full=False):
        logged_in = False
        try:
            health = self._request('GET', '/healthz')
            if health != dict(status='ready', release=self.release, schema=1):
                raise DeploymentError('Public health does not match the selected release.')
            if self._request('POST', '/api/session', json={'code': self.password}) != {'signed_in': True}:
                raise DeploymentError('Hosted login did not succeed.')
            logged_in = True
            session = self._request('GET', '/api/session')
            if (session['providers'] != list(self.config.providers) or session['models'] != self.config.models()):
                raise DeploymentError('Hosted provider configuration differs from the selected release.')
            baseline = self._request('GET', '/api/office')
            scenario = self._request('POST', '/api/office/scenario', json=CONTROLS)
            if baseline['bill']['total_usd'] != '6710.80' or scenario['scenario_bill']['total_usd'] != '6344.11':
                raise DeploymentError('Hosted prepared scenario differs from independently expected totals.')
            checked = []
            if full:
                document_path = self._bills()
                for provider in self.config.providers:
                    self._provider(provider, document_path)
                    checked.append(provider)
                self._request('DELETE', document_path)
            result = dict(health=True, login=True, office_scenario=True, bill_upload_review=full, providers=checked)
            if full:
                result['history'] = self._history()
            return result
        except DeploymentError:
            raise
        except Exception:
            raise DeploymentError('Hosted journey failed; response details suppressed.') from None
        finally:
            if logged_in:
                # Try logout even after the verification deadline, without leaking response content.
                try:
                    response = self.client.delete('/api/session', headers=self.headers)
                    if response.status_code != 200:
                        raise ValueError()
                except Exception:
                    raise DeploymentError('Hosted verification session cleanup failed; it expires automatically.') from None
